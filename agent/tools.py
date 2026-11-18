from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

import config

CRITIC_TOOL = {
    "type": "function",
    "function": {
        "name": "analyze_restaurant_photo",
        "description": (
            "Analyze a restaurant photo (interior, facade, dining room). "
            "Call this whenever the user sends a photo of a venue (not just a dish). "
            "Returns venue level, status, atmosphere, and confidence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_note": {
                    "type": "string",
                    "description": "Short description of what is visible in the attached photo.",
                }
            },
            "required": ["image_note"],
        },
    },
}


def analyze_restaurant_photo(image_url: str) -> dict[str, Any]:
    """Vision skill: classify restaurant level, status, and atmosphere from a photo."""
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    prompt = (
        "Ты ресторанный критик. По фото заведения оцени:\n"
        "1) level: fastfood | casual | mid-range | fine dining\n"
        "2) status: семейный | романтический | бизнес-ланч | молодёжный | туристический | другое\n"
        "3) description: 2-3 предложения про атмосферу и аудиторию\n"
        "4) confidence: 0..1\n"
        "Верни только JSON с ключами level, status, description, confidence."
    )
    if image_url.startswith("data:") or image_url.startswith("http"):
        image_part: dict[str, Any] = {"url": image_url, "detail": "low"}
    else:
        image_part = {"url": image_url, "detail": "low"}

    response = client.chat.completions.create(
        model=config.OPENAI_VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": image_part},
                ],
            }
        ],
        response_format={"type": "json_object"},
        max_tokens=400,
    )
    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)
    return {
        "level": data.get("level", "casual"),
        "status": data.get("status", "другое"),
        "description": data.get("description", ""),
        "confidence": float(data.get("confidence", 0.5)),
    }


def openai_tools_extra() -> list[dict[str, Any]]:
    return [CRITIC_TOOL]
