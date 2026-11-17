# Backend TTS para Gaélico Escocés (FastAPI + Meta MMS en Render)

Esta guía documenta la construcción y despliegue de un microservicio en **Python (FastAPI)** dedicado exclusivamente a **Gaélico Escocés** (*Gàidhlig*, código ISO `gla` / `gd`), utilizando el modelo neuronal `facebook/mms-tts-gla` de Meta y listo para alojarse en **Render**.

Al enfocarse en un solo idioma:
* **Consumo de memoria mínimo:** Se carga un único checkpoint en RAM (~250 MB).
* **Audio Disk Cache:** Cada palabra o frase se procesa una sola vez; luego se sirve directamente desde disco en milisegundos.
* **Precarga Batch:** Endpoint dedicado para generar de un solo tirón todo tu listado inicial de frases.

---

## 1. Estructura del Proyecto

```text
gaelic-tts-service/
├── app/
│   ├── __init__.py
│   ├── main.py
│   └── tts_engine.py
├── audio_cache/          # Directorio local o Persistent Disk
├── Dockerfile
├── requirements.txt
├── render.yaml
└── phrases.json          # Tu lista inicial de frases y palabras
```

---

## 2. Dependencias

### `requirements.txt`

```text
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
torch>=2.2.0 --extra-index-url https://download.pytorch.org/whl/cpu
transformers>=4.41.0
scipy>=1.13.0
soundfile>=0.12.1
pydantic>=2.7.0
```

---

## 3. Código del Microservicio

### `app/tts_engine.py`

Gestiona el modelo de Gaélico Escocés y la caché en disco por hash MD5.

```python
import os
import io
import hashlib
from typing import Tuple, Optional
import soundfile as sf
import torch
from transformers import AutoTokenizer, VitsModel

# Modelo especializado en Gaélico Escocés (Gàidhlig)
MODEL_ID = "facebook/mms-tts-gla"
CACHE_DIR = os.getenv("AUDIO_CACHE_DIR", "./audio_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


class ScottishGaelicTTS:
    def __init__(self):
        self.tokenizer: Optional[AutoTokenizer] = None
        self.model: Optional[VitsModel] = None

    def _load_model(self):
        """Carga el modelo en memoria sólo en la primera petición para no bloquear el inicio."""
        if self.model is None or self.tokenizer is None:
            self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
            self.model = VitsModel.from_pretrained(MODEL_ID)
            self.model.eval()

    def _get_cache_path(self, text: str) -> Tuple[str, str]:
        normalized = text.strip().lower()
        file_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()
        filename = f"gd_{file_hash}.wav"
        return os.path.join(CACHE_DIR, filename), filename

    def synthesize(self, text: str) -> Tuple[str, bytes]:
        """
        Devuelve (filename, bytes_wav). Si ya existe en caché, no corre inferencia.
        """
        filepath, filename = self._get_cache_path(text)

        # 1. Recuperar de caché si existe
        if os.path.exists(filepath):
            with open(filepath, "rb") as f:
                return filename, f.read()

        # 2. Inferencia con Meta MMS
        self._load_model()
        inputs = self.tokenizer(text, return_tensors="pt")

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

        return filename, audio_bytes


tts_engine = ScottishGaelicTTS()
```

### `app/main.py`

```python
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.tts_engine import tts_engine

app = FastAPI(
    title="Scottish Gaelic TTS API",
    description="Servicio de síntesis de voz para Gaélico Escocés (Gàidhlig)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    text: str = Field(..., example="Madainn mhath, ciamar a tha sibh?")


class BatchItem(BaseModel):
    id: Optional[str] = Field(None, example="phrase_01")
    text: str = Field(..., example="Tapadh leibh gu mòr")


class BatchRequest(BaseModel):
    items: List[BatchItem]


@app.get("/health")
def health():
    return {"status": "ok", "language": "Scottish Gaelic (gla)"}


@app.post("/synthesize")
def synthesize(payload: TTSRequest):
    """Sintetiza la frase en gaélico escocés y devuelve el stream WAV directamente."""
    try:
        filename, audio_bytes = tts_engine.synthesize(payload.text)
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/batch-preload")
def batch_preload(payload: BatchRequest):
    """
    Precarga y cachea en disco una lista de palabras/frases.
    Ideal para ejecutarlo una sola vez post-deploy.
    """
    summary = []
    for item in payload.items:
        try:
            filename, _ = tts_engine.synthesize(item.text)
            summary.append({"id": item.id, "text": item.text, "file": filename, "status": "cached"})
        except Exception as exc:
            summary.append({"id": item.id, "text": item.text, "status": "failed", "error": str(exc)})

    return {"total": len(payload.items), "results": summary}
```

---

## 4. Dockerfile

```dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    AUDIO_CACHE_DIR=/app/audio_cache

WORKDIR /app

# Dependencias para I/O de audio
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN mkdir -p /app/audio_cache

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 5. Despliegue en Render

Podés usar un archivo `render.yaml` o crear el Web Service desde la consola:

### `render.yaml`

```yaml
services:
  - type: web
    name: scottish-gaelic-tts
    env: docker
    plan: starter
    region: oregon
    healthCheckPath: /health
    disk:
      name: gaelic-audio-cache
      mountPath: /app/audio_cache
      sizeGB: 1
    envVars:
      - key: AUDIO_CACHE_DIR
        value: /app/audio_cache
```

> **Consejo sobre el disco:** Si agregás un *Persistent Disk* (`/app/audio_cache`), los audios que precargues no se perderán nunca aunque Render reinicie o actualice el contenedor.

---

## 6. Precarga de tu Listado Inicial

Podés armar un archivo `phrases.json` con tu lista particular de frases y dispararlo contra tu backend:

```json
{
  "items": [
    { "id": "p01", "text": "Halò" },
    { "id": "p02", "text": "Madainn mhath" },
    { "id": "p03", "text": "Feasgar math" },
    { "id": "p04", "text": "Ciamar a tha sibh?" },
    { "id": "p05", "text": "Tha gu math, tapadh leibh" },
    { "id": "p06", "text": "Mar sin leibh" },
    { "id": "p07", "text": "Oidhche mhath" }
  ]
}
```

Y precargarlas con un solo comando:

```bash
curl -X POST "https://tu-servicio.onrender.com/batch-preload" \
     -H "Content-Type: application/json" \
     -d @phrases.json
```

A partir de ese momento, cada vez que un usuario o tu frontend pida `"Madainn mhath"`, la API devolverá el `.wav` instantáneamente sin gastar CPU en re-sintetizar.