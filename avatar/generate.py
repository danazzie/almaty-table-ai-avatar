from __future__ import annotations

import hashlib
from pathlib import Path

import fal_client

import config
from voice.tts import download_url

PROMPT = (
    "4K studio interview, medium close-up. "
    "Soft key-light, light-grey backdrop. "
    "Presenter faces lens, steady eye-contact. Ultra-sharp."
)

_photo_url_cache: str | None = None


def _photo_url() -> str:
    """Upload the avatar photo once per process and reuse the URL."""
    global _photo_url_cache
    if config.AVATAR_PHOTO_URL:
        return config.AVATAR_PHOTO_URL
    if _photo_url_cache is None:
        if not config.PHOTO_PATH.exists():
            raise RuntimeError(f"Add a frontal portrait at {config.PHOTO_PATH}")
        _photo_url_cache = fal_client.upload_file(str(config.PHOTO_PATH))
    return _photo_url_cache


def generate_avatar_video(audio_path: str | Path) -> str | None:
    """Creatify Aurora lip-sync video; cached by audio content hash.

    Every Aurora run costs real money, so identical audio never re-renders.
    """
    if not config.ENABLE_AVATAR:
        return None

    audio_bytes = Path(audio_path).read_bytes()
    digest = hashlib.sha256(audio_bytes).hexdigest()[:16]
    cached = config.OUTPUT_DIR / f"avatar_{digest}.mp4"
    if cached.exists() and cached.stat().st_size > 0:
        return str(cached)

    audio_url = fal_client.upload_file(str(audio_path))
    result = fal_client.subscribe(
        "fal-ai/creatify/aurora",
        arguments={
            "image_url": _photo_url(),
            "audio_url": audio_url,
            "prompt": PROMPT,
            "guidance_scale": 1,
            "audio_guidance_scale": 2,
            "resolution": "720p",
        },
    )
    video = result.get("video") or {}
    url = video.get("url") if isinstance(video, dict) else None
    if not url:
        raise RuntimeError(f"Avatar generation failed: {result}")
    return download_url(url, cached)
