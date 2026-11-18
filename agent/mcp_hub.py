from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import config

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 30
TOOL_TIMEOUT_S = 120


class MCPHub:
    """Runs the 2GIS and Chocolife MCP servers as separate stdio subprocesses.

    anyio requires stdio_client's context to be entered and exited in the same
    task, so each server lives inside its own long-running asyncio task that
    holds the `async with` blocks open until shutdown.
    """

    SERVERS: dict[str, Path] = {
        "twogis": config.TWOGIS_SERVER,
        "chocolife": config.CHOCOLIFE_SERVER,
    }

    def __init__(self) -> None:
        self._sessions: dict[str, ClientSession] = {}
        self._tasks: list[asyncio.Task] = []
        self._shutdown = asyncio.Event()
        self._openai_tools: list[dict[str, Any]] = []
        self._tool_owner: dict[str, str] = {}
        self.status: dict[str, str] = {name: "not started" for name in self.SERVERS}
        self.started = False

    async def _server_task(self, name: str, script: Path, ready: asyncio.Event) -> None:
        params = StdioServerParameters(
            # sys.executable guarantees the venv interpreter even if `python`
            # on PATH points elsewhere (e.g. conda base).
            command=sys.executable,
            args=[str(script)],
            cwd=str(config.ROOT),
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._sessions[name] = session
                    self.status[name] = "connected"
                    ready.set()
                    await self._shutdown.wait()
        except Exception as exc:
            self.status[name] = f"error: {exc}"
            logger.exception("MCP server %s failed", name)
            ready.set()
        finally:
            self._sessions.pop(name, None)

    async def start(self) -> None:
        """Spawn all servers; a single failing server degrades, not crashes."""
        if self.started:
            return
        ready_events: list[asyncio.Event] = []
        for name, script in self.SERVERS.items():
            ready = asyncio.Event()
            ready_events.append(ready)
            self._tasks.append(asyncio.create_task(self._server_task(name, script, ready)))
        for ready in ready_events:
            try:
                await asyncio.wait_for(ready.wait(), timeout=CONNECT_TIMEOUT_S)
            except asyncio.TimeoutError:
                pass
        await self._refresh_tools()
        self.started = True

    async def _refresh_tools(self) -> None:
        self._openai_tools = []
        self._tool_owner = {}
        for name, session in self._sessions.items():
            listed = await session.list_tools()
            for tool in listed.tools:
                self._tool_owner[tool.name] = name
                schema = (
                    getattr(tool, "input_schema", None)
                    or getattr(tool, "inputSchema", None)
                    or {"type": "object", "properties": {}}
                )
                self._openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or tool.name,
                            "parameters": schema,
                        },
                    }
                )

    def openai_tools(self, extra: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        tools = list(self._openai_tools)
        if extra:
            tools.extend(extra)
        return tools

    def owner_of(self, tool_name: str) -> str | None:
        return self._tool_owner.get(tool_name)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        owner = self._tool_owner.get(name)
        session = self._sessions.get(owner) if owner else None
        if not session:
            return json.dumps({"error": f"Unknown or offline tool {name}"}, ensure_ascii=False)
        try:
            result = await asyncio.wait_for(session.call_tool(name, arguments), timeout=TOOL_TIMEOUT_S)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return json.dumps({"error": f"{name} failed: {exc}"}, ensure_ascii=False)
        parts = [getattr(block, "text", None) or str(block) for block in result.content]
        return "\n".join(parts) if parts else json.dumps({"ok": True})

    async def close(self) -> None:
        self._shutdown.set()
        for task in self._tasks:
            try:
                await asyncio.wait_for(task, timeout=5)
            except Exception:
                task.cancel()
        self._tasks.clear()
        self.started = False
