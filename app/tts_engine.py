import gc
import hashlib
import io
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape

import soundfile as sf
import torch
from transformers import AutoTokenizer, VitsModel

# Voces oficiales de Azure Speech para Galés (cy-GB)
AZURE_WELSH_VOICES: Dict[str, str] = {
    "nia": "cy-GB-NiaNeural",
    "cy-gb-nianeural": "cy-GB-NiaNeural",
    "aled": "cy-GB-AledNeural",
    "cy-gb-aledneural": "cy-GB-AledNeural",
}

DEFAULT_AZURE_WELSH_VOICE = os.getenv("AZURE_WELSH_VOICE", "cy-GB-NiaNeural")

# Modelos Meta MMS (Licencia CC-BY-NC 4.0: uso exclusivo de revisión interna / borrador no comercial)
MMS_MODELS: Dict[str, str] = {
    "gd": "facebook/mms-tts-gla",  # Gaélico escocés (Gàidhlig) - borrador en revisión
    "cy": "facebook/mms-tts-cym",  # Galés (Cymraeg) - sólo si ALLOW_MMS_FALLBACK=true
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
        raise ValueError(
            f"Idioma no soportado: '{lang}'. Use 'gd' (Gaélico escocés) o 'cy' (Galés)."
        )
    return LANGUAGE_ALIASES[cleaned]


def normalize_welsh_voice(voice: Optional[str] = None) -> str:
    raw = (voice or DEFAULT_AZURE_WELSH_VOICE).strip()
    key = raw.lower()
    if key in AZURE_WELSH_VOICES:
        return AZURE_WELSH_VOICES[key]
    raise ValueError(
        f"Voz de Galés no válida: '{voice}'. Voces soportadas en Azure: 'cy-GB-NiaNeural' (Nia) o 'cy-GB-AledNeural' (Aled)."
    )


def normalize_text_key(text: str) -> str:
    return " ".join(text.strip().split())


class SolturaTTSEngine:
    def __init__(self):
        self.current_mms_lang: Optional[str] = None
        self.tokenizer: Optional[AutoTokenizer] = None
        self.model: Optional[VitsModel] = None

        # Índices del manifest de Soltura:
        self.items_by_id: Dict[str, dict] = {}
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
                    }
                    norm = normalize_text_key(text)
                    self.id_by_lang_text[(lang, norm)] = item_id
                    self.id_by_lang_text_lower[(lang, norm.lower())] = item_id
            except Exception as exc:
                print(f"[WARN] No se pudo cargar el manifest {path}: {exc}")

    def _load_mms_model(self, lang: str):
        """
        Carga un único checkpoint de Meta MMS en RAM (~250 MB) para revisión/borrador.
        """
        lang = normalize_language(lang)
        model_id = MMS_MODELS[lang]

        if self.current_mms_lang == lang and self.model is not None and self.tokenizer is not None:
            return

        if self.model is not None or self.tokenizer is not None:
            self.model = None
            self.tokenizer = None
            self.current_mms_lang = None
            gc.collect()

        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = VitsModel.from_pretrained(model_id)
        self.model.eval()
        self.current_mms_lang = lang

    def resolve_item(
        self,
        text: Optional[str] = None,
        language: Optional[str] = None,
        item_id: Optional[str] = None,
    ) -> Tuple[str, str, str]:
        """
        Resuelve (resolved_id, resolved_lang, resolved_text).
        Si coincide con un item de Soltura, usa su ID oficial (ej. 'gd-13e686b645a2570e' o 'cy-ec43e481f8caaa20').
        """
        if item_id:
            clean_id = item_id[:-4] if item_id.endswith(".wav") else item_id
            if clean_id in self.items_by_id:
                entry = self.items_by_id[clean_id]
                resolved_text = text.strip() if text else entry["text"]
                return clean_id, entry["language"], resolved_text
            if not text:
                raise KeyError(
                    f"No se encontró el ID '{clean_id}' en el manifest y no se envió 'text'."
                )
            lang = normalize_language(language, clean_id)
            return clean_id, lang, text.strip()

        if not text or not text.strip():
            raise ValueError("El campo 'text' no puede estar vacío.")

        lang = normalize_language(language)
        norm = normalize_text_key(text)

        matched_id = self.id_by_lang_text.get((lang, norm)) or self.id_by_lang_text_lower.get(
            (lang, norm.lower())
        )
        if matched_id:
            return matched_id, lang, text.strip()

        file_hash = hashlib.md5(norm.encode("utf-8")).hexdigest()
        return f"{lang}_{file_hash}", lang, text.strip()

    def get_cache_path(self, resolved_id: str) -> Tuple[Path, str]:
        clean_id = resolved_id[:-4] if resolved_id.endswith(".wav") else resolved_id
        filename = f"{clean_id}.wav"
        return CACHE_DIR / filename, filename

    def get_meta_path(self, resolved_id: str) -> Path:
        clean_id = resolved_id[:-4] if resolved_id.endswith(".wav") else resolved_id
        return CACHE_DIR / f"{clean_id}.meta.json"

    def is_cached(self, resolved_id: str) -> bool:
        filepath, _ = self.get_cache_path(resolved_id)
        return filepath.exists()

    def read_metadata(self, resolved_id: str, lang: str, text: str) -> dict:
        meta_path = self.get_meta_path(resolved_id)
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        # Metadatos por defecto si el archivo existe pero no tenía .meta.json
        if lang == "cy":
            return {
                "id": resolved_id,
                "language": "cy",
                "locale": "cy-GB",
                "text": text,
                "provider": "azure-speech",
                "voice": DEFAULT_AZURE_WELSH_VOICE,
                "license": "Microsoft Azure Commercial",
                "commercialUseAllowed": True,
                "version": "1.0",
            }
        return {
            "id": resolved_id,
            "language": "gd",
            "locale": "gd-GB",
            "text": text,
            "provider": "meta-mms",
            "voice": MMS_MODELS["gd"],
            "license": "CC-BY-NC-4.0 (Borrador en revisión docente - No comercial)",
            "commercialUseAllowed": False,
            "version": "1.0-draft",
        }

    def write_metadata(self, resolved_id: str, meta: dict):
        meta_path = self.get_meta_path(resolved_id)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _synthesize_azure_welsh(self, text: str, voice: Optional[str] = None) -> Tuple[bytes, dict]:
        """
        Sintetiza Galés (cy-GB) con Azure Cognitive Services Speech (voces neuronales Nia o Aled).
        Cumple con condiciones comerciales de Azure cuando se usa con suscripción de pago.
        """
        api_key = os.getenv("AZURE_SPEECH_KEY", "").strip()
        region = os.getenv("AZURE_SPEECH_REGION", "eastus").strip()
        selected_voice = normalize_welsh_voice(voice)

        if not api_key:
            allow_fallback = os.getenv("ALLOW_MMS_FALLBACK", "false").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            if allow_fallback:
                audio_bytes = self._synthesize_mms("cy", text)
                return audio_bytes, {
                    "provider": "meta-mms-fallback",
                    "voice": MMS_MODELS["cy"],
                    "license": "CC-BY-NC-4.0 (Fallback de prueba - No comercial)",
                    "commercialUseAllowed": False,
                    "version": "1.0-draft",
                }
            raise RuntimeError(
                "Para generar audios en Galés (cy) con Azure Speech configurá las variables de entorno "
                "AZURE_SPEECH_KEY y AZURE_SPEECH_REGION (voces cy-GB-NiaNeural / cy-GB-AledNeural). "
                "Si solo querés hacer una prueba técnica no comercial con Meta MMS, definí ALLOW_MMS_FALLBACK=true."
            )

        endpoint = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        escaped_text = xml_escape(text)
        ssml = (
            f"<speak version='1.0' xml:lang='cy-GB'>"
            f"<voice xml:lang='cy-GB' name='{selected_voice}'>{escaped_text}</voice>"
            f"</speak>"
        )

        req = urllib.request.Request(
            endpoint,
            data=ssml.encode("utf-8"),
            headers={
                "Ocp-Apim-Subscription-Key": api_key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                "User-Agent": "Soltura-TTS-Service/1.2",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                audio_bytes = resp.read()
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Error de Azure Speech ({exc.code}): {err_body or exc.reason}"
            ) from exc

        return audio_bytes, {
            "provider": "azure-speech",
            "voice": selected_voice,
            "license": "Microsoft Azure Commercial",
            "commercialUseAllowed": True,
            "version": "1.0",
        }

    def _synthesize_mms(self, lang: str, text: str) -> bytes:
        self._load_mms_model(lang)
        inputs = self.tokenizer(text, return_tensors="pt")

        with torch.no_grad():
            output = self.model(**inputs).waveform

        waveform = output.squeeze().cpu().numpy()
        sample_rate = self.model.config.sampling_rate

        buffer = io.BytesIO()
        sf.write(buffer, waveform, samplerate=sample_rate, format="WAV")
        return buffer.getvalue()

    def synthesize(
        self,
        text: Optional[str] = None,
        language: Optional[str] = "gd",
        item_id: Optional[str] = None,
        voice: Optional[str] = None,
        force_regenerate: bool = False,
    ) -> Tuple[str, bytes, dict]:
        """
        Devuelve (filename, bytes_wav, metadata).
        1. Si el archivo ya existe en audio_cache/ (por ej. generado una vez con Azure o grabado por la profe),
           lo sirve directamente desde disco sin llamar a ningún motor externo.
        2. Si no existe:
           - Para Galés ('cy'): usa Azure Speech (voces neuronales cy-GB-NiaNeural o cy-GB-AledNeural).
           - Para Gaélico escocés ('gd'): usa Meta MMS como borrador en revisión docente (marcado CC-BY-NC-4.0).
        """
        resolved_id, lang, resolved_text = self.resolve_item(
            text=text, language=language, item_id=item_id
        )
        filepath, filename = self.get_cache_path(resolved_id)

        # 1. Recuperar de caché si existe
        if filepath.exists() and not force_regenerate:
            meta = self.read_metadata(resolved_id, lang, resolved_text)
            meta["cache"] = "HIT"
            with open(filepath, "rb") as f:
                return filename, f.read(), meta

        # 2. Generar según la estrategia por idioma de Soltura
        if lang == "cy":
            audio_bytes, provider_meta = self._synthesize_azure_welsh(resolved_text, voice=voice)
            locale = "cy-GB"
        else:
            audio_bytes = self._synthesize_mms("gd", resolved_text)
            locale = "gd-GB"
            provider_meta = {
                "provider": "meta-mms",
                "voice": MMS_MODELS["gd"],
                "license": "CC-BY-NC-4.0 (Borrador en revisión docente - No comercial)",
                "commercialUseAllowed": False,
                "version": "1.0-draft",
            }

        # 3. Guardar audio y metadatos de trazabilidad (proveedor/modelo/voz, licencia y versión)
        with open(filepath, "wb") as f:
            f.write(audio_bytes)

        meta = {
            "id": resolved_id,
            "language": lang,
            "locale": locale,
            "text": resolved_text,
            **provider_meta,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }
        self.write_metadata(resolved_id, meta)
        meta["cache"] = "MISS"

        return filename, audio_bytes, meta


tts_engine = SolturaTTSEngine()
