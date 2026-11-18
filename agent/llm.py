from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

import config
from agent.mcp_hub import MCPHub
from agent.tools import analyze_restaurant_photo, openai_tools_extra

SYSTEM_PROMPT = """Ты персональный гид по ресторанам Алматы.
Всегда используй MCP-инструменты для фактов: search_restaurants (2GIS) и search_deals (Chocolife).
Не выдумывай адреса, рейтинги и цены — опирайся на результаты tools.
Если пользователь прислал фото заведения — вызови analyze_restaurant_photo и учти оценку в рекомендации.
Если фото блюда — опиши его и подбери похожие места в Алматы через tools.
Ответ на русском, живой, конкретный: 2–4 заведения, почему подходят, бюджет, если есть акции.
Держи ответ коротким (15–30 секунд устной речи, примерно до 80–90 слов), чтобы озвучка и видео не были слишком длинными.
"""

MAX_TOOL_ROUNDS = 8


def _limit_reply(text: str) -> str:
    """Keep answers within ~15–30s of speech, cutting at a sentence boundary."""
    if len(text) <= config.MAX_REPLY_CHARS:
        return text
    cut = text[: config.MAX_REPLY_CHARS]
    for sep in (". ", "! ", "? ", "\n"):
        idx = cut.rfind(sep)
        if idx > config.MAX_REPLY_CHARS // 2:
            return cut[: idx + 1].strip()
    return cut.rsplit(" ", 1)[0] + "…"


@dataclass
class ToolEvent:
    """One tool invocation, kept for UI transparency and debugging."""

    tool: str
    server: str
    arguments: dict[str, Any]
    duration_ms: int
    result_preview: str


@dataclass
class AgentReply:
    text: str
    tool_events: list[ToolEvent] = field(default_factory=list)


class RestaurantAgent:
    def __init__(self, hub: MCPHub) -> None:
        self.hub = hub
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.history: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def reset(self) -> None:
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def _trim(self) -> None:
        """Trim old history without orphaning tool messages.

        The cut point must land on a user message: an assistant message with
        tool_calls followed by role="tool" replies is an atomic unit for the
        OpenAI API, and splitting it causes 400 errors.
        """
        if len(self.history) <= config.SESSION_HISTORY_LIMIT + 1:
            return
        tail = self.history[-config.SESSION_HISTORY_LIMIT:]
        start = 0
        while start < len(tail) and tail[start].get("role") != "user":
            start += 1
        self.history = [self.history[0]] + tail[start:]

    async def reply(self, user_text: str, image_data_url: str | None = None) -> AgentReply:
        content: Any
        if image_data_url:
            content = [
                {"type": "text", "text": user_text or "Проанализируй это фото в контексте ресторанов Алматы."},
                {"type": "image_url", "image_url": {"url": image_data_url, "detail": "low"}},
            ]
        else:
            content = user_text
        self.history.append({"role": "user", "content": content})
        self._trim()

        events: list[ToolEvent] = []
        tools = self.hub.openai_tools(openai_tools_extra())
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=self.history,
                tools=tools,
                tool_choice="auto",
            )
            message = response.choices[0].message
            if not message.tool_calls:
                text = _limit_reply((message.content or "").strip())
                self.history.append({"role": "assistant", "content": text})
                return AgentReply(text=text, tool_events=events)

            self.history.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in message.tool_calls
                    ],
                }
            )
            for tc in message.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                started = time.monotonic()
                if tc.function.name == "analyze_restaurant_photo":
                    server = "vision-critic"
                    if not image_data_url:
                        tool_result = json.dumps({"error": "no image attached"})
                    else:
                        tool_result = json.dumps(analyze_restaurant_photo(image_data_url), ensure_ascii=False)
                else:
                    server = self.hub.owner_of(tc.function.name) or "mcp"
                    tool_result = await self.hub.call_tool(tc.function.name, args)
                events.append(
                    ToolEvent(
                        tool=tc.function.name,
                        server=server,
                        arguments=args,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        result_preview=tool_result[:300],
                    )
                )
                self.history.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result})
        return AgentReply(
            text="Не удалось получить ответ от инструментов. Попробуйте ещё раз.",
            tool_events=events,
        )
