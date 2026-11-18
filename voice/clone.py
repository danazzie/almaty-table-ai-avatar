"""Optional: clone a new voice. Skip if voice_id.txt / MINIMAX_VOICE_ID already exists."""

from __future__ import annotations

import sys
from pathlib import Path

import fal_client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402


def clone_voice() -> str:
    if not config.FAL_KEY:
        raise SystemExit("Set FAL_KEY / FALAI_API_KEY in .env")
    sample = config.VOICE_SAMPLE_PATH
    if not sample.exists():
        raise SystemExit(f"Put a 10+ second WAV at {sample}")

    audio_url = config.VOICE_SAMPLE_URL or fal_client.upload_file(str(sample))
    result = fal_client.subscribe(
        "fal-ai/minimax/voice-clone",
        arguments={
            "audio_url": audio_url,
            "preview_text": "Привет! Это тест клонированного голоса гида по ресторанам Алматы.",
            "language": "Russian",
        },
    )
    voice_id = result.get("voice_id") or result.get("custom_voice_id")
    if not voice_id:
        raise SystemExit(f"Unexpected clone response: {result}")
    (ROOT / "voice_id.txt").write_text(str(voice_id), encoding="utf-8")
    print(f"Saved voice_id={voice_id} to voice_id.txt")
    print("Also set MINIMAX_VOICE_ID in .env")
    return str(voice_id)


if __name__ == "__main__":
    clone_voice()
