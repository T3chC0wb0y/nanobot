from __future__ import annotations

from typing import Any

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.local_memory import (
    LocalMemoryConfig,
    build_capture_request,
    capture_candidate,
    classify_recall_need,
    ensure_risky_action_allowed,
    has_local_memory_server,
    search_local_memory,
    should_capture_candidate,
    write_recall_trace,
)
from nanobot.agent.tools.registry import ToolRegistry


class LocalMemoryHook(AgentHook):
    """Agent hook that injects compact local-memory recall.

    This hook is intentionally supplemental. It never replaces Nanobot's native
    USER.md / SOUL.md / MEMORY.md / history.jsonl context.
    """

    def __init__(self, config: LocalMemoryConfig, tools: ToolRegistry) -> None:
        super().__init__()
        self._config = config
        self._tools = tools

    async def before_iteration(self, context: AgentHookContext) -> None:
        tools = self._tools
        if not self._config.enabled or not has_local_memory_server(tools, self._config.server_name):
            return
        if context.iteration != 0:
            return
        user_text = _latest_user_text(context.messages)
        if not user_text and not self._config.enable_bootstrap_recall:
            return
        if not user_text:
            user_text = "continue with active project context and user preferences"
        decision = classify_recall_need(user_text, self._config)
        if not decision.should_recall:
            return
        recall = await search_local_memory(tools, user_text, self._config)
        ignored = []
        used_memory_ids = list(recall.memory_ids if recall else [])
        if not recall or not recall.content:
            if decision.risky:
                ignored.append({"memory_id": "*", "reason": "no_relevant_promoted_guidance_found"})
                write_recall_trace(
                    self._config,
                    task_summary=user_text,
                    decision=decision,
                    recall=recall,
                    used_memory_ids=[],
                    ignored=ignored,
                )
                ensure_risky_action_allowed(user_text, recall)
                return
            write_recall_trace(
                self._config,
                task_summary=user_text,
                decision=decision,
                recall=recall,
                used_memory_ids=[],
                ignored=ignored or [{"memory_id": "*", "reason": "no_results"}],
            )
            return
        _insert_supplemental_system_message(
            context.messages,
            f"{recall.heading}:\n{recall.content}",
        )
        write_recall_trace(
            self._config,
            task_summary=user_text,
            decision=decision,
            recall=recall,
            used_memory_ids=used_memory_ids,
            ignored=ignored,
        )
        ensure_risky_action_allowed(user_text, recall)

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        return

    async def after_iteration(self, context: AgentHookContext) -> None:
        tools = self._tools
        if not self._config.enabled or not has_local_memory_server(tools, self._config.server_name):
            return
        if context.stop_reason != "completed" or not context.final_content:
            return
        user_text = _latest_user_text(context.messages)
        if not should_capture_candidate(user_text, context.final_content, self._config):
            return
        request = build_capture_request(user_text, context.final_content, self._config)
        if request is None:
            return
        await capture_candidate(tools, request, self._config)


def _insert_supplemental_system_message(messages: list[dict[str, Any]], content: str) -> None:
    message = {"role": "system", "content": content}
    if messages and messages[0].get("role") == "system":
        messages.insert(1, message)
        return
    messages.insert(0, message)


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
            return "\n".join(parts).strip()
    return ""

