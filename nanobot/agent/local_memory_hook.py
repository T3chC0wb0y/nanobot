from __future__ import annotations

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.local_memory import (
    LocalMemoryConfig,
    build_capture_request,
    capture_candidate,
    has_local_memory_server,
    search_local_memory,
    should_capture_candidate,
    should_search_local_memory,
)
from nanobot.agent.messages import build_system_message


class LocalMemoryHook(AgentHook):
    def __init__(self, config: LocalMemoryConfig) -> None:
        self._config = config

    def _tools(self, context: AgentHookContext):
        return context.agent.tools

    async def before_iteration(self, context: AgentHookContext) -> None:
        tools = self._tools(context)
        if not self._config.enabled or not has_local_memory_server(tools, self._config.server_name):
            return
        if context.iteration != 1:
            return
        user_text = _latest_user_text(context.messages)
        if not should_search_local_memory(user_text, self._config):
            return
        injection = await search_local_memory(tools, user_text, self._config)
        if not injection or not injection.content:
            return
        context.messages.insert(
            0,
            build_system_message(f"{injection.heading}:\n{injection.content}"),
        )

    async def after_iteration(self, context: AgentHookContext) -> None:
        tools = self._tools(context)
        if not self._config.enabled or not has_local_memory_server(tools, self._config.server_name):
            return
        if context.stop_reason != "done" or not context.final_content:
            return
        user_text = _latest_user_text(context.messages)
        if not should_capture_candidate(user_text, context.final_content, self._config):
            return
        request = build_capture_request(user_text, context.final_content, self._config)
        if request is None:
            return
        await capture_candidate(tools, request, self._config)


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
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
