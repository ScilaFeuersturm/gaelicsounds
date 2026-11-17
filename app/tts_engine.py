import gc
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import soundfile as sf
import torch
from transformers import AutoTokenizer, VitsModel

# Modelos Meta MMS por idioma soportado en Soltura
LANGUAGE_MODELS: Dict[str, str] = {
    "gd": "facebook/mms-tts-gla",  # Gaélico escocés (Gàidhlig)
    "cy": "facebook/mms-tts-cym",  # Galés (Cymraeg)
}

LANGUAGE_ALIASES: Dict[str, str] = {
    "gd": "gd",
    "gd-gb": "gd",
    "gla": "gd",
    "cy": "cy",
    "cy-gb": "cy",
    "cym": "cy",
}

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.getenv("AUDIO_CACHE_DIR", str(BASE_DIR / "audio_cache")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_PATHS = [
    BASE_DIR / "Listados-audio-Soltura" / "gaelico-escoces-gd" / "manifest-audios.json",
    BASE_DIR / "Listados-audio-Soltura" / "gales-cy" / "manifest-audios.json",
    BASE_DIR / "Listados-Audio-soltura" / "gaelico-escoces-gd" / "manifest-audios.json",
    BASE_DIR / "Listados-Audio-soltura" / "gales-cy" / "manifest-audios.json",
]


def normalize_language(lang: Optional[str], item_id: Optional[str] = None) -> str:
    if item_id:
        prefix = item_id.split("-", 1)[0].lower()
        if prefix in LANGUAGE_ALIASES:
            return LANGUAGE_ALIASES[prefix]
    if not lang:
        return "gd"
    cleaned = lang.strip().lower()
    if cleaned not in LANGUAGE_ALIASES:
        raise ValueError(f"Idioma no soportado: '{lang}'. Use 'gd' (Gaélico escocés) o 'cy' (Galés).")
    return LANGUAGE_ALIASES[cleaned]


def normalize_text_key(text: str) -> str:
    return " ".join(text.strip().split())


class SolturaTTSEngine:
    def __init__(self):
        self.current_lang: Optional[str] = None
        self.tokenizer: Optional[AutoTokenizer] = None
        self.model: Optional[VitsModel] = None

        # Índices del manifest de Soltura:
        # id -> dict del item
        self.items_by_id: Dict[str, dict] = {}
        # (lang, texto_exacto) -> id y (lang, texto_lower) -> id
        self.id_by_lang_text: Dict[Tuple[str, str], str] = {}
        self.id_by_lang_text_lower: Dict[Tuple[str, str], str] = {}

        self._load_manifests()

    def _load_manifests(self):
        """Carga los manifests de Soltura (gd y cy) para resolver IDs estables y textos."""
        for path in MANIFEST_PATHS:
            if not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                default_lang = data.get("language", "gd")
                for item in data.get("items", []):
                    item_id = item.get("id")
                    text = item.get("text", "").strip()
                    lang = normalize_language(item.get("language", default_lang), item_id)
                    if not item_id or not text:
                        continue
                    self.items_by_id[item_id] = {
                        **item,
                        "language": lang,
                        "model": LANGUAGE_MODELS[lang],
                    }
                    norm = normalize_text_key(text)
                    self.id_by_lang_text[(lang, norm)] = item_id
                    self.id_by_lang_text_lower[(lang, norm.lower())] = item_id
            except Exception as exc:
                print(f"[WARN] No se pudo cargar el manifest {path}: {exc}")

    def _load_model(self, lang: str):
        """
        Carga un único checkpoint en RAM a la vez (~250 MB) para minimizar consumo de memoria en Render.
        """
        lang = normalize_language(lang)
        model_id = LANGUAGE_MODELS[lang]

        if self.current_lang == lang and self.model is not None and self.tokenizer is not None:
            return

        # Liberar modelo previo si cambiamos de idioma
        if self.model is not None or self.tokenizer is not None:
            self.model = None
            self.tokenizer = None
            self.current_lang = None
            gc.collect()

        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = VitsModel.from_pretrained(model_id)
        self.model.eval()
        self.current_lang = lang

    def resolve_item(
        self,
        text: Optional[str] = None,
        language: Optional[str] = None,
        item_id: Optional[str] = None,
    ) -> Tuple[str, str, str]:
        """
        Resuelve (resolved_id, resolved_lang, resolved_text).
        Si coincide con un item de Soltura, usa su ID oficial (ej. 'gd-13e686b645a2570e').
        Si es texto libre nuevo, genera un ID determinístico '<lang>_<md5>'.
        """
        if item_id:
            clean_id = item_id[:-4] if item_id.endswith(".wav") else item_id
            if clean_id in self.items_by_id:
                entry = self.items_by_id[clean_id]
                resolved_text = text.strip() if text else entry["text"]
                return clean_id, entry["language"], resolved_text
            if not text:
                raise KeyError(f"No se encontró el ID '{clean_id}' en el manifest y no se envió 'text'.")
            lang = normalize_language(language, clean_id)
            return clean_id, lang, text.strip()

        if not text or not text.strip():
            raise ValueError("El campo 'text' no puede estar vacío.")

        lang = normalize_language(language)
        norm = normalize_text_key(text)

        # Buscar coincidencia exacta primero (respeta Cymru vs Gymru), luego case-insensitive
        matched_id = self.id_by_lang_text.get((lang, norm)) or self.id_by_lang_text_lower.get(
            (lang, norm.lower())
        )
        if matched_id:
            return matched_id, lang, text.strip()

        # Fallback por hash MD5 (conservando mayúsculas/minúsculas o texto normalizado en UTF-8)
        file_hash = hashlib.md5(norm.encode("utf-8")).hexdigest()
        return f"{lang}_{file_hash}", lang, text.strip()

    def get_cache_path(self, resolved_id: str) -> Tuple[Path, str]:
        clean_id = resolved_id[:-4] if resolved_id.endswith(".wav") else resolved_id
        filename = f"{clean_id}.wav"
        return CACHE_DIR / filename, filename

    def is_cached(self, resolved_id: str) -> bool:
        filepath, _ = self.get_cache_path(resolved_id)
        return filepath.exists()

    def synthesize(
        self,
        text: Optional[str] = None,
        language: Optional[str] = "gd",
        item_id: Optional[str] = None,
        force_regenerate: bool = False,
    ) -> Tuple[str, bytes, dict]:
        """
        Devuelve (filename, bytes_wav, metadata).
        Si el archivo ya existe en caché en disco, lo devuelve en milisegundos sin correr inferencia.
        """
        resolved_id, lang, resolved_text = self.resolve_item(
            text=text, language=language, item_id=item_id
        )
        filepath, filename = self.get_cache_path(resolved_id)
        model_id = LANGUAGE_MODELS[lang]

        # 1. Recuperar de caché si existe
        if filepath.exists() and not force_regenerate:
            with open(filepath, "rb") as f:
                return (
                    filename,
                    f.read(),
                    {
                        "id": resolved_id,
                        "language": lang,
                        "model": model_id,
                        "cache": "HIT",
                        "text": resolved_text,
                    },
                )

        # 2. Inferencia con Meta MMS
        self._load_model(lang)
        inputs = self.tokenizer(resolved_text, return_tensors="pt")

        with torch.no_grad():
            output = self.model(**inputs).waveform

        waveform = output.squeeze().cpu().numpy()
        sample_rate = self.model.config.sampling_rate

        # 3. Guardar en buffer y en disco
        buffer = io.BytesIO()
        sf.write(buffer, waveform, samplerate=sample_rate, format="WAV")
        audio_bytes = buffer.getvalue()

        with open(filepath, "wb") as f:
            f.write(audio_bytes)

        return (
            filename,
            audio_bytes,
            {
                "id": resolved_id,
                "language": lang,
                "model": model_id,
                "cache": "MISS",
                "text": resolved_text,
            },
        )


tts_engine = SolturaTTSEngine()
