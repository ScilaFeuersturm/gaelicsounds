#!/usr/bin/env python3
"""
Script para generar de una sola vez todos los audios de Galés (cy-GB) de Soltura
usando Microsoft Azure Speech (voces neuronales comerciales cy-GB-NiaNeural o cy-GB-AledNeural).

Guarda cada archivo .wav y su .meta.json (proveedor, voz, licencia, versión) en audio_cache/.
Uso:
  export AZURE_SPEECH_KEY="tu_clave_de_azure"
  export AZURE_SPEECH_REGION="eastus"
  python3 scripts/generate_azure_welsh.py --voice cy-GB-NiaNeural
"""

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.tts_engine import tts_engine  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="Genera los audios de Galés (cy-GB) de Soltura con Azure Speech (Nia / Aled)."
    )
    parser.add_argument(
        "--voice",
        default="cy-GB-NiaNeural",
        help="Voz de Azure Speech: 'cy-GB-NiaNeural' (femenina, default) o 'cy-GB-AledNeural' (masculina)",
    )
    parser.add_argument(
        "--priority",
        type=int,
        choices=[1, 2],
        default=None,
        help="Filtrar por prioridad: 1 (70 principales) o 2 (8 complementarios). Por defecto genera los 78.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerar aunque el archivo .wav ya exista en audio_cache/",
    )
    args = parser.parse_args()

    welsh_items = [
        (item_id, entry)
        for item_id, entry in tts_engine.items_by_id.items()
        if entry.get("language") == "cy"
        and (args.priority is None or entry.get("priority") == args.priority)
    ]

    print(f"Generando {len(welsh_items)} audios de Galés (cy-GB) con voz '{args.voice}'...")
    ok_count = 0
    for idx, (item_id, entry) in enumerate(welsh_items, start=1):
        text = entry["text"]
        try:
            filename, _, meta = tts_engine.synthesize(
                text=text,
                language="cy",
                item_id=item_id,
                voice=args.voice,
                force_regenerate=args.force,
            )
            ok_count += 1
            print(
                f"[{idx:02d}/{len(welsh_items)}] OK {filename} ({meta['cache']}) -> {text}"
            )
        except Exception as exc:
            print(f"[{idx:02d}/{len(welsh_items)}] ERROR {item_id} ({text}): {exc}")
            sys.exit(1)

    print(
        f"\n¡Listo! {ok_count}/{len(welsh_items)} audios guardados en 'audio_cache/' con su trazabilidad .meta.json."
    )


if __name__ == "__main__":
    main()
