from __future__ import annotations

import base64
import logging
from pathlib import Path

from openai import OpenAI

import config
from agent.llm import RestaurantAgent
from avatar.generate import generate_avatar_video
from voice.tts import synthesize

logger = logging.getLogger(__name__)


def transcribe(audio_path: str | Path) -> str:
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(model="whisper-1", file=f)
    return result.text.strip()


def image_to_data_url(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    suffix = Path(path).suffix.lower().lstrip(".") or "jpeg"
    mime = "image/png" if suffix == "png" else "image/jpeg"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def run_turn(
    agent: RestaurantAgent,
    text: str,
    audio_path: str | None,
    image_path: str | None,
) -> dict:
    """Full pipeline for one turn: ASR -> LLM (+tools) -> TTS -> Avatar."""
    user_text = (text or "").strip()
    transcript = ""
    if audio_path:
        transcript = transcribe(audio_path)
        user_text = transcript + (("\n" + user_text) if user_text else "")
    if not user_text and not image_path:
        return {
            "text": "Напишите вопрос, запишите голос или загрузите фото.",
            "audio": None,
            "video": None,
            "transcript": "",
            "tool_events": [],
        }

    image_url = image_to_data_url(image_path) if image_path else None
    reply = await agent.reply(user_text or "Что это за место?", image_url)

    audio_out = None
    video_out = None
    media_error = ""
    if config.ENABLE_TTS:
        try:
            audio_out = synthesize(reply.text)
        except Exception as exc:
            logger.exception("TTS failed")
            media_error = f"Озвучка не удалась: {exc}"
    if config.ENABLE_AVATAR and audio_out:
        try:
            video_out = generate_avatar_video(audio_out)
        except Exception as exc:
            logger.exception("Avatar failed")
            media_error = f"Видео-аватар не удался: {exc}"

    return {
        "text": reply.text,
        "audio": audio_out,
        "video": video_out,
        "transcript": transcript,
        "tool_events": reply.tool_events,
        "media_error": media_error,
    }
