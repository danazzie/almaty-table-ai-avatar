from __future__ import annotations

import hashlib
from pathlib import Path

import fal_client
import httpx

import config


def download_url(url: str, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=180) as client:
        r = client.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return str(dest)


def synthesize(text: str) -> str | None:
    """Generate speech with the cloned MiniMax voice; cache by text hash.

    Caching means repeated demo runs of the same answer are free.
    """
    if not config.ENABLE_TTS:
        return None
    if not config.MINIMAX_VOICE_ID:
        raise RuntimeError("No MINIMAX_VOICE_ID. Set it in .env or voice_id.txt")

    digest = hashlib.sha256(f"{config.MINIMAX_VOICE_ID}:{text}".encode()).hexdigest()[:16]
    cached = config.OUTPUT_DIR / f"tts_{digest}.mp3"
    if cached.exists() and cached.stat().st_size > 0:
        return str(cached)

    result = fal_client.subscribe(
        "fal-ai/minimax/speech-02-turbo",
        arguments={
            "text": text,
            "voice_id": config.MINIMAX_VOICE_ID,
            "language": "Russian",
        },
    )
    audio = result.get("audio") or {}
    url = audio.get("url") if isinstance(audio, dict) else None
    if not url:
        url = result.get("audio_url")
    if not url:
        raise RuntimeError(f"TTS failed: {result}")
    return download_url(url, cached)
