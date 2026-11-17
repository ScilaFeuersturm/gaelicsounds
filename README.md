# gaelicsounds

Servicio de síntesis y provisión de audios para **Soltura**, diseñado con una estrategia separada por idioma para cuidar la **licencia comercial** y el **presupuesto**:

| Idioma | Código | Motor / Estrategia | Voces | Licencia | Estado |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Galés** (*Cymraeg*) | `cy` (`cy-GB`) | **Microsoft Azure Speech** (generación única + caché) | `cy-GB-NiaNeural` (Nia) / `cy-GB-AledNeural` (Aled) | **Comercial permitida** (Azure Paid Tier) | Listo para producción (78 textos) |
| **Gaélico escocés** (*Gàidhlig*) | `gd` (`gd-GB`) | **Archivos aprobados en `audio_cache/`** (profe / Ceitidh) + **Meta MMS** (`facebook/mms-tts-gla`) solo para borrador | Grabación docente / Ceitidh / MMS (draft) | **MMS es CC-BY-NC 4.0 (No comercial)** | En revisión docente (80 textos) |

---

## Trazabilidad de Proveedor, Voz y Licencia (`.meta.json`)

Siguiendo los criterios de `Listados-audio-Soltura/LEEME.md`, cada vez que se genera o aloja un audio en `audio_cache/{id}.wav`, el servicio guarda automáticamente un archivo `audio_cache/{id}.meta.json` (y lo expone en `GET /manifest` y en los headers HTTP `X-TTS-*`) con:

```json
{
  "id": "cy-ec43e481f8caaa20",
  "language": "cy",
  "locale": "cy-GB",
  "text": "Cymru",
  "provider": "azure-speech",
  "voice": "cy-GB-NiaNeural",
  "license": "Microsoft Azure Commercial",
  "commercialUseAllowed": true,
  "version": "1.0",
  "generatedAt": "2026-11-17T13:55:00+00:00"
}
```

---

## Cómo generar los 78 audios de Galés (`cy`) una sola vez con Azure

Podés generar los 78 archivos `.wav` de Galés una única vez y dejarlos guardados en `audio_cache/` (incluso commiteados al repositorio para que en el plan **Free** de Render nunca se borren ni consuman cuota adicional):

### Opción A: Script local (`scripts/generate_azure_welsh.py`)
```bash
export AZURE_SPEECH_KEY="tu_clave_de_azure"
export AZURE_SPEECH_REGION="eastus"

# Generar con la voz femenina Nia (por defecto) o masculina Aled (--voice cy-GB-AledNeural)
python3 scripts/generate_azure_welsh.py --voice cy-GB-NiaNeural
```
Luego podés subir los `.wav` y `.meta.json` generados en `audio_cache/` a GitHub para que queden permanentes en Render Free.

### Opción B: Desde el endpoint `/batch-preload` en Render
Configurá `AZURE_SPEECH_KEY` y `AZURE_SPEECH_REGION` en la pestaña **Environment** de Render y ejecutá:
```bash
# Generar los 70 textos principales de Galés con Nia
curl -X POST "https://gaelicsounds.onrender.com/batch-preload?language=cy&priority=1&voice=cy-GB-NiaNeural"
```

---

## Cómo usar los Audios de Gaélico Escocés (`gd`)

* **Mientras está en revisión docente (uso interno no comercial):**
  El servicio puede sintetizar borradores con `facebook/mms-tts-gla` marcándolos explícitamente con `"commercialUseAllowed": false` y `"license": "CC-BY-NC-4.0"`.
* **Cuando tengan las grabaciones de la docente o Ceitidh:**
  Basta con guardar los archivos `.wav` en `audio_cache/` usando el ID estable del manifest (por ejemplo `audio_cache/gd-13e686b645a2570e.wav`). El backend detecta automáticamente que el archivo ya existe en `audio_cache/` y lo sirve de inmediato sin invocar a Meta MMS.

---

## Cómo consumir el Backend desde Soltura

URL en Render: **`https://gaelicsounds.onrender.com`**

### 1. Reproducir por ID estable del manifest (`GET /audio/{id}.wav`)
```html
<!-- Galés (Azure Nia/Aled): "Cymru" -->
<audio src="https://gaelicsounds.onrender.com/audio/cy-ec43e481f8caaa20.wav" controls></audio>

<!-- Gaélico escocés: "Gàidhlig" -->
<audio src="https://gaelicsounds.onrender.com/audio/gd-13e686b645a2570e.wav" controls></audio>
```

Desde TypeScript / JavaScript en Soltura:
```ts
const AUDIO_API = "https://gaelicsounds.onrender.com";

export function getSolturaAudioUrl(id: string): string {
  return `${AUDIO_API}/audio/${id}.wav`;
}
```

### 2. Consultar el catálogo, estado de caché y licencias (`GET /manifest`)
```bash
# Ver estado y metadatos de Galés
curl "https://gaelicsounds.onrender.com/manifest?language=cy"

# Ver estado y metadatos de Gaélico escocés
curl "https://gaelicsounds.onrender.com/manifest?language=gd"
```

### 3. Sintetizar por texto (`GET /synthesize` y `POST /synthesize`)
```bash
curl -X POST "https://gaelicsounds.onrender.com/synthesize" \
     -H "Content-Type: application/json" \
     -d '{"text": "Bore da", "language": "cy", "voice": "cy-GB-NiaNeural"}' \
     --output bore_da.wav
```

### 4. Health Check y estado de configuración (`GET /health`)
```bash
curl "https://gaelicsounds.onrender.com/health"
```
