from __future__ import annotations

import asyncio
import json
import threading

import gradio as gr

import config
from agent.llm import RestaurantAgent
from agent.mcp_hub import MCPHub
from agent.pipeline import run_turn

_loop = asyncio.new_event_loop()
_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_thread.start()

hub = MCPHub()
agent: RestaurantAgent | None = None

CSS = """
.gradio-container {
  max-width: 1240px !important;
  font-family: "Source Serif 4", Georgia, serif !important;
}
.hero {
  background:
    radial-gradient(ellipse at top right, rgba(212, 120, 48, 0.35), transparent 55%),
    linear-gradient(135deg, #241a12 0%, #3d2617 55%, #6e3018 100%);
  border-radius: 20px;
  padding: 26px 30px;
  color: #f7efe6;
  border: 1px solid rgba(232, 196, 150, 0.25);
}
.hero h1 { font-size: 1.85rem; margin: 0 0 6px 0; letter-spacing: 0.02em; color: #fff7ec; }
.hero p { margin: 0; opacity: 0.9; font-size: 0.98rem; }
.pills { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
.pill {
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: 12px;
  padding: 4px 12px;
  border-radius: 999px;
  background: rgba(255,255,255,0.12);
  border: 1px solid rgba(255,255,255,0.2);
}
.pill.on  { background: #2f6f4e; border-color: #4cae80; }
.pill.off { background: rgba(0,0,0,0.3); }
.trace { font-size: 0.85rem; }
footer { display: none !important; }
"""

THEME = gr.themes.Soft(
    primary_hue="orange",
    secondary_hue="stone",
    neutral_hue="stone",
    font=gr.themes.GoogleFont("Source Serif 4"),
    font_mono=gr.themes.GoogleFont("IBM Plex Mono"),
).set(
    body_background_fill="#1c1814",
    body_text_color="#f3e9dc",
    block_background_fill="#26201b",
    block_border_color="#3d332b",
    block_label_text_color="#e8c496",
    button_primary_background_fill="#c45c26",
    button_primary_background_fill_hover="#d96a2e",
    button_primary_text_color="#fffaf4",
    border_color_accent="#c45c26",
)

SERVER_LABELS = {"twogis": "2GIS", "chocolife": "Chocolife", "vision-critic": "Ресторанный критик"}


def _run(coro):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


async def _ensure_agent() -> RestaurantAgent:
    global agent
    if agent is None:
        await hub.start()
        agent = RestaurantAgent(hub)
    return agent


def _mcp_status_md() -> str:
    if not hub.started:
        return "MCP-серверы запустятся при первом вопросе."
    rows = []
    for name, status in hub.status.items():
        icon = "🟢" if status == "connected" else "🔴"
        rows.append(f"{icon} **{SERVER_LABELS.get(name, name)}** — {status}")
    return "<br>".join(rows)


def _trace_md(events) -> str:
    if not events:
        return "_В этом ответе инструменты не вызывались._"
    lines = []
    for i, ev in enumerate(events, 1):
        args = json.dumps(ev.arguments, ensure_ascii=False)
        server = SERVER_LABELS.get(ev.server, ev.server)
        lines.append(
            f"**{i}. `{ev.tool}`** · {server} · {ev.duration_ms} ms\n"
            f"   - аргументы: `{args}`\n"
            f"   - результат: `{ev.result_preview[:160]}…`"
        )
    return "\n".join(lines)


def respond(message, audio, image, history):
    history = history or []
    shown = (message or "").strip()
    badges = []
    if audio:
        badges.append("🎤 голос")
    if image:
        badges.append("📷 фото")
    if badges:
        shown = (shown + "\n" if shown else "") + " · ".join(badges)
    history.append({"role": "user", "content": shown or "…"})

    async def _job():
        a = await _ensure_agent()
        return await run_turn(a, message or "", audio, image)

    try:
        result = _run(_job())
        reply = result["text"]
        if result.get("transcript"):
            reply = f"*Распознано: «{result['transcript']}»*\n\n{reply}"
        if result.get("media_error"):
            reply += f"\n\n⚠️ {result['media_error']}"
        audio_out, video_out = result["audio"], result["video"]
        trace = _trace_md(result.get("tool_events", []))
    except Exception as exc:
        reply = f"⚠️ Не удалось получить ответ: {exc}"
        audio_out, video_out, trace = None, None, "_Ошибка до вызова инструментов._"

    history.append({"role": "assistant", "content": reply})
    return history, audio_out, video_out, history, "", None, None, trace, _mcp_status_md()


def reset_chat():
    if agent:
        agent.reset()
    return [], None, None, [], "", None, None, "_Диалог сброшен._", _mcp_status_md()


tts_state = "on" if config.ENABLE_TTS else "off"
avatar_state = "on" if config.ENABLE_AVATAR else "off"
photo_ok = config.PHOTO_PATH.exists()
voice_ok = bool(config.MINIMAX_VOICE_ID)

with gr.Blocks(title="Almaty Table — AI Avatar Guide") as demo:
    gr.HTML(
        f"""
        <div class="hero">
          <h1>🍽 Almaty Table</h1>
          <p>Мультимодальный AI-гид по ресторанам Алматы: живые данные 2GIS и Chocolife,
             клонированный голос и говорящий аватар.</p>
          <div class="pills">
            <span class="pill on">MCP · 2GIS + Chocolife</span>
            <span class="pill {tts_state}">Озвучка {tts_state}</span>
            <span class="pill {avatar_state}">Аватар {avatar_state}</span>
            <span class="pill {'on' if voice_ok else 'off'}">{'Голос клонирован' if voice_ok else 'Нет voice id'}</span>
            <span class="pill {'on' if photo_ok else 'off'}">{'Фото аватара готово' if photo_ok else 'Нет avatar/my_photo.jpg'}</span>
          </div>
        </div>
        """
    )

    with gr.Row(equal_height=False):
        with gr.Column(scale=7):
            chatbot = gr.Chatbot(
                label="Диалог с гидом",
                height=460,
                placeholder="Спросите, где поесть в Алматы — текстом, голосом или фото.",
                avatar_images=(None, str(config.PHOTO_PATH) if photo_ok else None),
            )
            text = gr.Textbox(
                label="Ваш вопрос",
                placeholder="Где поужинать в центре Алматы на двоих, бюджет 15 000 тенге?",
                lines=2,
                max_lines=4,
                autofocus=True,
            )
            with gr.Row():
                send = gr.Button("Спросить гида", variant="primary", scale=2)
                clear = gr.Button("Новый диалог", scale=1)
            gr.Examples(
                examples=[
                    ["Где поужинать в центре Алматы на двоих, бюджет 15 000 тенге?"],
                    ["Кафе с завтраками рядом с Достык Plaza"],
                    ["Какие сейчас акции на рестораны на Chocolife?"],
                    ["Романтический ужин, итальянская кухня, средний чек"],
                ],
                inputs=[text],
                label="Попробуйте спросить",
            )
            with gr.Accordion("🎤 Голос и 📷 фото", open=False):
                with gr.Row():
                    audio = gr.Audio(
                        label="Голосовой вопрос (Whisper ASR)",
                        sources=["microphone", "upload"],
                        type="filepath",
                    )
                    image = gr.Image(
                        label="Фото блюда или интерьера (vision + критик)",
                        type="filepath",
                        height=220,
                    )

        with gr.Column(scale=4):
            out_video = gr.Video(label="🎬 Говорящий аватар", height=300)
            out_audio = gr.Audio(label="🔊 Клонированный голос", type="filepath")
            with gr.Accordion("🔧 Вызовы инструментов (последний ответ)", open=True):
                trace_md = gr.Markdown("_Пока пусто — задайте вопрос._", elem_classes=["trace"])
            with gr.Accordion("📡 Статус MCP-серверов", open=False):
                status_md = gr.Markdown(_mcp_status_md())
            gr.Markdown(
                "Озвучка и видео включаются флагами `ENABLE_TTS` / `ENABLE_AVATAR` в `.env`. "
                "Повторные ответы берутся из кэша и не тратят бюджет."
            )

    state = gr.State([])
    outputs = [chatbot, out_audio, out_video, state, text, audio, image, trace_md, status_md]
    send.click(respond, [text, audio, image, state], outputs)
    text.submit(respond, [text, audio, image, state], outputs)
    clear.click(reset_chat, None, outputs)


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1)
    demo.launch(theme=THEME, css=CSS)
