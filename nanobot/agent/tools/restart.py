"""Restart tool for agent-triggered gateway restarts."""

from __future__ import annotations

import asyncio
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema


@tool_parameters(
    tool_parameters_schema(
        reason=StringSchema(
            "Optional short reason for the restart request, for logging/audit purposes."
        ),
        required=[],
    )
)
class RestartTool(Tool):
    """Tool to trigger a configured gateway restart command."""

    def __init__(self, *, enabled: bool | None = None, command: str | None = None):
        self._enabled = enabled
        self._command = command.strip() if isinstance(command, str) else None

    @property
    def name(self) -> str:
        return "restart"

    @property
    def description(self) -> str:
        return (
            "Trigger a configured nanobot gateway restart command. "
            "Only available when explicitly enabled by the operator."
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        return True

    def _resolve_settings(self) -> tuple[bool, str]:
        if self._enabled is not None or self._command is not None:
            return bool(self._enabled), self._command or ""

        try:
            from nanobot.config.loader import load_config

            cfg = load_config()
            return (
                bool(getattr(cfg.gateway, "agent_restart_enabled", False)),
                str(getattr(cfg.gateway, "agent_restart_command", "") or "").strip(),
            )
        except Exception:
            return False, ""

    async def execute(self, reason: str | None = None, **kwargs: Any) -> str:
        enabled, command = self._resolve_settings()
        if not enabled:
            return "Error: agent-triggered restart is disabled"
        if not command:
            return "Error: no restart command configured"

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            return f"Error: failed to start restart command: {e}"

        extra = f" Reason: {reason.strip()}" if isinstance(reason, str) and reason.strip() else ""
        return (
            f"Gateway restart command started (pid: {process.pid})."
            f"{extra}"
        )
