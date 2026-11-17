from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.tts_engine import LANGUAGE_MODELS, tts_engine

app = FastAPI(
    title="Soltura Gaelic & Welsh TTS API",
    description=(
        "Servicio de síntesis de voz para Soltura: "
        "Gaélico Escocés (Gàidhlig, gd) y Galés (Cymraeg, cy) con Meta MMS y caché en disco."
    ),
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    text: str = Field(..., json_schema_extra={"example": "Madainn mhath"})
    language: Optional[str] = Field(
        "gd",
        description="Código de idioma: 'gd' (Gaélico escocés, por defecto) o 'cy' (Galés)",
        json_schema_extra={"example": "gd"},
    )
    id: Optional[str] = Field(
        None,
        description="ID estable opcional del manifest de Soltura (ej. 'gd-f6c1f5638cdcea4b')",
        json_schema_extra={"example": "gd-f6c1f5638cdcea4b"},
    )


class BatchItem(BaseModel):
    id: Optional[str] = Field(None, json_schema_extra={"example": "gd-f6c1f5638cdcea4b"})
    text: str = Field(..., json_schema_extra={"example": "Madainn mhath"})
    language: Optional[str] = Field("gd", json_schema_extra={"example": "gd"})


class BatchRequest(BaseModel):
    items: Optional[List[BatchItem]] = Field(
        None,
        description=(
            "Lista de frases a precargar. Si se omite, precarga automáticamente "
            "los textos del manifest de Soltura."
        ),
    )


def _audio_response(filename: str, audio_bytes: bytes, meta: dict) -> Response:
    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Audio-Id": str(meta.get("id", "")),
            "X-TTS-Language": str(meta.get("language", "")),
            "X-TTS-Model": str(meta.get("model", "")),
            "X-Cache-Status": str(meta.get("cache", "")),
        },
    )


@app.get("/health")
def health():
    total_manifest = len(tts_engine.items_by_id)
    cached_manifest = sum(1 for item_id in tts_engine.items_by_id if tts_engine.is_cached(item_id))
    return {
        "status": "ok",
        "supported_languages": LANGUAGE_MODELS,
        "loaded_model_language": tts_engine.current_lang,
        "soltura_manifest": {
            "total_items": total_manifest,
            "cached_items": cached_manifest,
        },
    }


@app.get("/manifest")
def list_manifest(
    language: Optional[str] = Query(None, description="Filtrar por 'gd' o 'cy'"),
    priority: Optional[int] = Query(None, description="Filtrar por prioridad (1=principales, 2=complementarios)"),
):
    """
    Devuelve el catálogo de audios de Soltura junto con su estado en caché y su URL directa (/audio/{id}.wav).
    """
    items = []
    for item_id, entry in tts_engine.items_by_id.items():
        if language and entry.get("language") != language:
            continue
        if priority is not None and entry.get("priority") != priority:
            continue
        items.append(
            {
                "id": item_id,
                "language": entry.get("language"),
                "locale": entry.get("locale"),
                "text": entry.get("text"),
                "translations": entry.get("translations", []),
                "levels": entry.get("levels", []),
                "priority": entry.get("priority"),
                "kind": entry.get("kind"),
                "model": entry.get("model"),
                "cached": tts_engine.is_cached(item_id),
                "audioUrl": f"/audio/{item_id}.wav",
            }
        )
    return {"total": len(items), "items": items}


@app.get("/audio/{item_id}")
def get_audio_by_id(
    item_id: str,
    text: Optional[str] = Query(None, description="Texto opcional si el ID no está en el manifest"),
    language: Optional[str] = Query(None, description="Idioma opcional ('gd' o 'cy')"),
):
    """
    Endpoint ideal para consumir desde Soltura (<audio src=".../audio/gd-13e686b645a2570e.wav">).
    Si el audio ya está en caché lo sirve al instante; si no, lo sintetiza y guarda en disco.
    """
    try:
        filename, audio_bytes, meta = tts_engine.synthesize(
            text=text, language=language, item_id=item_id
        )
        return _audio_response(filename, audio_bytes, meta)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/synthesize")
def synthesize_get(
    text: str = Query(..., description="Texto a sintetizar"),
    language: str = Query("gd", description="Idioma: 'gd' (Gaélico escocés) o 'cy' (Galés)"),
    id: Optional[str] = Query(None, description="ID opcional de Soltura"),
):
    """Permite consumir la síntesis directamente por URL con GET."""
    try:
        filename, audio_bytes, meta = tts_engine.synthesize(
            text=text, language=language, item_id=id
        )
        return _audio_response(filename, audio_bytes, meta)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/synthesize")
def synthesize_post(payload: TTSRequest):
    """Sintetiza la frase y devuelve el stream WAV directamente."""
    try:
        filename, audio_bytes, meta = tts_engine.synthesize(
            text=payload.text, language=payload.language, item_id=payload.id
        )
        return _audio_response(filename, audio_bytes, meta)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/batch-preload")
def batch_preload(
    payload: Optional[BatchRequest] = None,
    language: Optional[str] = Query(
        None, description="Si no se envía body, filtra el manifest por 'gd' o 'cy'"
    ),
    priority: Optional[int] = Query(
        None, description="Si no se envía body, filtra por prioridad (1=principales, 2=complementarios)"
    ),
):
    """
    Precarga y cachea en disco una lista de palabras/frases.
    - Si se envía {"items": [...]}, procesa esa lista (ej. phrases.json).
    - Si se llama sin body, precarga automáticamente los textos del manifest de Soltura.
    """
    items_to_process: List[BatchItem] = []

    if payload and payload.items:
        items_to_process = payload.items
    else:
        for item_id, entry in tts_engine.items_by_id.items():
            if language and entry.get("language") != language:
                continue
            if priority is not None and entry.get("priority") != priority:
                continue
            items_to_process.append(
                BatchItem(id=item_id, text=entry["text"], language=entry["language"])
            )

    summary = []
    for item in items_to_process:
        try:
            filename, _, meta = tts_engine.synthesize(
                text=item.text, language=item.language, item_id=item.id
            )
            summary.append(
                {
                    "id": meta["id"],
                    "language": meta["language"],
                    "text": item.text,
                    "file": filename,
                    "audioUrl": f"/audio/{filename}",
                    "cache": meta["cache"],
                    "status": "cached",
                }
            )
        except Exception as exc:
            summary.append(
                {
                    "id": item.id,
                    "language": item.language,
                    "text": item.text,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    return {"total": len(items_to_process), "results": summary}
