import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.tts_engine import (
    AZURE_WELSH_VOICES,
    DEFAULT_AZURE_WELSH_VOICE,
    MMS_MODELS,
    tts_engine,
)

app = FastAPI(
    title="Soltura Audio & TTS Service (Welsh Azure + Scottish Gaelic Review)",
    description=(
        "Servicio de audios para Soltura: "
        "Galés (cy-GB) con voces neuronales comerciales de Azure (Nia / Aled) "
        "y Gaélico Escocés (gd-GB) en revisión docente / borrador."
    ),
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    text: str = Field(..., json_schema_extra={"example": "Bore da"})
    language: Optional[str] = Field(
        "gd",
        description="Código de idioma: 'cy' (Galés - Azure Nia/Aled) o 'gd' (Gaélico escocés - en revisión)",
        json_schema_extra={"example": "cy"},
    )
    id: Optional[str] = Field(
        None,
        description="ID estable opcional del manifest de Soltura (ej. 'cy-cb87f9af2a17aec0')",
        json_schema_extra={"example": "cy-cb87f9af2a17aec0"},
    )
    voice: Optional[str] = Field(
        None,
        description="Voz opcional para Galés en Azure: 'cy-GB-NiaNeural' ('nia') o 'cy-GB-AledNeural' ('aled')",
        json_schema_extra={"example": "cy-GB-NiaNeural"},
    )
    force_regenerate: Optional[bool] = Field(
        False,
        description="Si es true, vuelve a generar el audio aunque ya exista en caché",
    )


class BatchItem(BaseModel):
    id: Optional[str] = Field(None, json_schema_extra={"example": "cy-cb87f9af2a17aec0"})
    text: str = Field(..., json_schema_extra={"example": "Bore da"})
    language: Optional[str] = Field("cy", json_schema_extra={"example": "cy"})
    voice: Optional[str] = Field(None, json_schema_extra={"example": "cy-GB-NiaNeural"})


class BatchRequest(BaseModel):
    items: Optional[List[BatchItem]] = Field(
        None,
        description=(
            "Lista de frases a precargar. Si se omite, precarga automáticamente "
            "los textos del manifest de Soltura según los filtros."
        ),
    )
    voice: Optional[str] = Field(
        None,
        description="Voz de Azure para los ítems en Galés ('cy-GB-NiaNeural' o 'cy-GB-AledNeural')",
    )
    force_regenerate: Optional[bool] = Field(False)


def _audio_response(filename: str, audio_bytes: bytes, meta: dict) -> Response:
    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Audio-Id": str(meta.get("id", "")),
            "X-TTS-Language": str(meta.get("language", "")),
            "X-TTS-Provider": str(meta.get("provider", "")),
            "X-TTS-Voice": str(meta.get("voice", "")),
            "X-TTS-License": str(meta.get("license", "")),
            "X-TTS-Commercial-Allowed": str(meta.get("commercialUseAllowed", "")),
            "X-TTS-Version": str(meta.get("version", "1.0")),
            "X-Cache-Status": str(meta.get("cache", "")),
        },
    )


@app.get("/health")
def health():
    total_manifest = len(tts_engine.items_by_id)
    cached_manifest = sum(
        1 for item_id in tts_engine.items_by_id if tts_engine.is_cached(item_id)
    )
    azure_configured = bool(os.getenv("AZURE_SPEECH_KEY", "").strip())
    return {
        "status": "ok",
        "strategy": {
            "cy": {
                "name": "Galés (Cymraeg)",
                "provider": "Azure Cognitive Services Speech",
                "voices": ["cy-GB-NiaNeural", "cy-GB-AledNeural"],
                "default_voice": DEFAULT_AZURE_WELSH_VOICE,
                "azure_key_configured": azure_configured,
                "license": "Microsoft Azure Commercial (Paid Tier)",
                "commercial_use_allowed": True,
            },
            "gd": {
                "name": "Gaélico escocés (Gàidhlig)",
                "status": "En revisión docente (sirve grabaciones aprobadas en caché o borrador MMS)",
                "draft_model": MMS_MODELS["gd"],
                "draft_license": "CC-BY-NC-4.0 (Solo revisión interna - No comercial)",
                "commercial_alternatives": ["Grabación docente propia", "CereProc Ceitidh"],
            },
        },
        "soltura_manifest": {
            "total_items": total_manifest,
            "cached_items": cached_manifest,
        },
    }


@app.get("/manifest")
def list_manifest(
    language: Optional[str] = Query(None, description="Filtrar por 'cy' o 'gd'"),
    priority: Optional[int] = Query(
        None, description="Filtrar por prioridad (1=principales, 2=complementarios)"
    ),
):
    """
    Devuelve el catálogo de audios de Soltura con su estado en caché, proveedor, voz, licencia y URL.
    """
    items = []
    for item_id, entry in tts_engine.items_by_id.items():
        lang = entry.get("language", "gd")
        if language and lang != language:
            continue
        if priority is not None and entry.get("priority") != priority:
            continue
        cached = tts_engine.is_cached(item_id)
        meta = (
            tts_engine.read_metadata(item_id, lang, entry.get("text", ""))
            if cached
            else None
        )
        items.append(
            {
                "id": item_id,
                "language": lang,
                "locale": entry.get("locale"),
                "text": entry.get("text"),
                "translations": entry.get("translations", []),
                "levels": entry.get("levels", []),
                "priority": entry.get("priority"),
                "kind": entry.get("kind"),
                "reviewStatus": entry.get("reviewStatus"),
                "cached": cached,
                "provenance": meta,
                "audioUrl": f"/audio/{item_id}.wav",
            }
        )
    return {"total": len(items), "items": items}


@app.get("/audio/{item_id}")
def get_audio_by_id(
    item_id: str,
    text: Optional[str] = Query(
        None, description="Texto opcional si el ID no está en el manifest"
    ),
    language: Optional[str] = Query(None, description="Idioma opcional ('cy' o 'gd')"),
    voice: Optional[str] = Query(
        None, description="Voz opcional para Galés ('cy-GB-NiaNeural' o 'cy-GB-AledNeural')"
    ),
):
    """
    Endpoint principal para Soltura (<audio src=".../audio/cy-ec43e481f8caaa20.wav">).
    Si el archivo ya fue generado y guardado en audio_cache/, lo reproduce directamente sin costo ni inferencia.
    """
    try:
        filename, audio_bytes, meta = tts_engine.synthesize(
            text=text, language=language, item_id=item_id, voice=voice
        )
        return _audio_response(filename, audio_bytes, meta)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/synthesize")
def synthesize_get(
    text: str = Query(..., description="Texto a sintetizar"),
    language: str = Query("cy", description="Idioma: 'cy' (Galés) o 'gd' (Gaélico escocés)"),
    id: Optional[str] = Query(None, description="ID opcional de Soltura"),
    voice: Optional[str] = Query(
        None, description="Voz opcional para Galés ('cy-GB-NiaNeural' o 'cy-GB-AledNeural')"
    ),
):
    try:
        filename, audio_bytes, meta = tts_engine.synthesize(
            text=text, language=language, item_id=id, voice=voice
        )
        return _audio_response(filename, audio_bytes, meta)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/synthesize")
def synthesize_post(payload: TTSRequest):
    try:
        filename, audio_bytes, meta = tts_engine.synthesize(
            text=payload.text,
            language=payload.language,
            item_id=payload.id,
            voice=payload.voice,
            force_regenerate=bool(payload.force_regenerate),
        )
        return _audio_response(filename, audio_bytes, meta)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/batch-preload")
def batch_preload(
    payload: Optional[BatchRequest] = None,
    language: Optional[str] = Query(
        None, description="Si no se envía body, filtra el manifest por 'cy' o 'gd'"
    ),
    priority: Optional[int] = Query(
        None,
        description="Si no se envía body, filtra por prioridad (1=principales, 2=complementarios)",
    ),
    voice: Optional[str] = Query(
        None, description="Voz de Azure para Galés ('cy-GB-NiaNeural' o 'cy-GB-AledNeural')"
    ),
):
    """
    Genera y guarda en disco (con sus metadatos .meta.json de proveedor, voz y licencia) una lista de frases.
    """
    items_to_process: List[BatchItem] = []
    default_voice = (payload.voice if payload and payload.voice else None) or voice
    force_regen = bool(payload.force_regenerate) if payload else False

    if payload and payload.items:
        items_to_process = payload.items
    else:
        for item_id, entry in tts_engine.items_by_id.items():
            if language and entry.get("language") != language:
                continue
            if priority is not None and entry.get("priority") != priority:
                continue
            items_to_process.append(
                BatchItem(
                    id=item_id,
                    text=entry["text"],
                    language=entry["language"],
                    voice=default_voice,
                )
            )

    summary = []
    for item in items_to_process:
        try:
            filename, _, meta = tts_engine.synthesize(
                text=item.text,
                language=item.language,
                item_id=item.id,
                voice=item.voice or default_voice,
                force_regenerate=force_regen,
            )
            summary.append(
                {
                    "id": meta["id"],
                    "language": meta["language"],
                    "text": item.text,
                    "file": filename,
                    "audioUrl": f"/audio/{filename}",
                    "provider": meta.get("provider"),
                    "voice": meta.get("voice"),
                    "license": meta.get("license"),
                    "commercialUseAllowed": meta.get("commercialUseAllowed"),
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
