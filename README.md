# gaelicsounds

Microservicio de síntesis de voz (**Text-to-Speech**) para **Soltura**, construido con **Python (FastAPI)** y los modelos neuronales **Meta MMS** (`facebook/mms-tts-gla` y `facebook/mms-tts-cym`), listo para desplegarse en **Render** con caché persistente en disco.

## Idiomas soportados

| Idioma | Código | Locale | Modelo Meta MMS | Textos en Manifest |
| :--- | :--- | :--- | :--- | :--- |
| **Gaélico escocés** (*Gàidhlig*) | `gd` (default) | `gd-GB` | `facebook/mms-tts-gla` | 80 (72 principales + 8 complementarios) |
| **Galés** (*Cymraeg*) | `cy` | `cy-GB` | `facebook/mms-tts-cym` | 78 (70 principales + 8 complementarios) |

* **Consumo de memoria mínimo:** Carga como máximo un único checkpoint en RAM a la vez (~250 MB).
* **Caché en disco (`audio_cache/`):** Cada frase se sintetiza una sola vez y se guarda con su **ID estable de Soltura** (por ejemplo, `gd-13e686b645a2570e.wav` o `cy-ec43e481f8caaa20.wav`). Las siguientes peticiones se sirven directamente desde disco en milisegundos sin correr inferencia.

---

## Estructura del Proyecto

```text
.
├── app/
│   ├── __init__.py
│   ├── main.py                  # Endpoints FastAPI + CORS
│   └── tts_engine.py            # Motor TTS Meta MMS + caché + lectura de manifests
├── Listados-Audio-soltura/      # Listados y manifests oficiales de Soltura (A1 y A2)
│   ├── LEEME.md
│   ├── gaelico-escoces-gd/
│   │   ├── 01-textos-necesarios.txt
│   │   ├── 02-practicas-complementarias.txt
│   │   ├── listado-con-contexto.csv
│   │   └── manifest-audios.json
│   └── gales-cy/
│       ├── 01-textos-necesarios.txt
│       ├── 02-practicas-complementarias.txt
│       ├── listado-con-contexto.csv
│       └── manifest-audios.json
├── audio_cache/                 # Directorio local o Persistent Disk en Render
├── phrases.json                 # Los 158 textos consolidados (gd + cy)
├── Dockerfile
├── render.yaml                  # Blueprint para Render
└── requirements.txt
```

---

## Cómo usar el Backend (Endpoints)

Una vez levantado el servicio (por ejemplo en `http://localhost:8000` o `https://scottish-gaelic-tts.onrender.com`), tenés disponibles los siguientes endpoints:

### 1. Obtener audio por ID de Soltura (`GET /audio/{id}`)
Ideal para usar directamente en etiquetas `<audio>` o `new Audio()` desde el frontend de Soltura. Acepta el ID con o sin extensión `.wav`. Si el audio ya está en disco lo devuelve al instante; si no, lo genera y lo guarda en caché automáticamente.

```html
<!-- Gaélico escocés: "Gàidhlig" -->
<audio src="https://tu-servicio.onrender.com/audio/gd-13e686b645a2570e.wav" controls></audio>

<!-- Galés: "Cymru" -->
<audio src="https://tu-servicio.onrender.com/audio/cy-ec43e481f8caaa20.wav" controls></audio>
```

Ejemplo desde JavaScript / TypeScript en Soltura:
```ts
const API_BASE = "https://tu-servicio.onrender.com";

export function playSolturaAudio(audioId: string) {
  const audio = new Audio(`${API_BASE}/audio/${audioId}.wav`);
  return audio.play();
}
```

---

### 2. Sintetizar por texto (`GET /synthesize` y `POST /synthesize`)
Si querés pedir un audio pasando el texto directamente:

* **Vía `GET`:**
  ```text
  GET /synthesize?text=Madainn%20mhath&language=gd
  GET /synthesize?text=Bore%20da&language=cy
  ```

* **Vía `POST`:**
  ```bash
  curl -X POST "https://tu-servicio.onrender.com/synthesize" \
       -H "Content-Type: application/json" \
       -d '{"text": "Madainn mhath", "language": "gd"}' \
       --output madainn_mhath.wav
  ```
  *(Si `language` se omite, usa `"gd"` por defecto).*

---

### 3. Precargar todos los audios en lote (`POST /batch-preload`)
Ideal para ejecutar una sola vez después del despliegue para que los 158 audios queden generados en el disco persistente:

* **Precargar todo el manifest integrado automáticamente (sin necesidad de adjuntar archivo):**
  ```bash
  curl -X POST "https://tu-servicio.onrender.com/batch-preload"
  ```

* **Precargar filtrando por idioma o prioridad (`1` = principales, `2` = complementarios):**
  ```bash
  # Solo Gaélico escocés (textos principales)
  curl -X POST "https://tu-servicio.onrender.com/batch-preload?language=gd&priority=1"

  # Solo Galés (textos principales)
  curl -X POST "https://tu-servicio.onrender.com/batch-preload?language=cy&priority=1"
  ```

* **O enviando un archivo JSON propio (`phrases.json`):**
  ```bash
  curl -X POST "https://tu-servicio.onrender.com/batch-preload" \
       -H "Content-Type: application/json" \
       -d @phrases.json
  ```

---

### 4. Consultar el catálogo y estado de caché (`GET /manifest`)
Devuelve el listado de frases de Soltura indicando si cada audio ya está generado en caché (`cached: true/false`), el modelo utilizado y su `audioUrl`:

```bash
curl "https://tu-servicio.onrender.com/manifest?language=gd"
```

### 5. Health Check (`GET /health`)
```bash
curl "https://tu-servicio.onrender.com/health"
```
Devuelve el estado del servicio, los idiomas soportados y cuántos ítems del manifest están cacheados en disco.

---

## Ejecución Local

1. **Crear entorno virtual e instalar dependencias:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Iniciar el servidor:**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

3. **Documentación interactiva (Swagger UI):**
   Abrí `http://localhost:8000/docs` en tu navegador para probar todos los endpoints.

---

## Despliegue en Render

El repositorio incluye un archivo `render.yaml` (Blueprint) y un `Dockerfile` listos para Render:

1. En el dashboard de [Render](https://dashboard.render.com/), seleccioná **New +** -> **Blueprint** (o **Web Service**) y conectá el repositorio `ScilaFeuersturm/gaelicsounds`.
2. Render detectará automáticamente el entorno `docker`, el health check `/health` y el disco persistente montado en `/app/audio_cache`.
3. Una vez finalizado el deploy, ejecutá `POST /batch-preload` para dejar todos los audios pregenerados en el disco persistente.
