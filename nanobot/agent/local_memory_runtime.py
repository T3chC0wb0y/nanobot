from __future__ import annotations

from typing import Any

from nanobot.agent.hook import AgentHook
from nanobot.agent.local_memory import LocalMemoryConfig
from nanobot.agent.local_memory_hook import LocalMemoryHook
from nanobot.agent.tools.registry import ToolRegistry


def build_local_memory_hooks(config: Any, tools: ToolRegistry) -> list[AgentHook]:
    """Build configured local-memory hooks for an AgentLoop."""
    local_cfg = getattr(getattr(config, "tools", None), "local_memory", None)
    if not local_cfg or not getattr(local_cfg, "enabled", False):
        return []

    memory_config = LocalMemoryConfig(
        enabled=local_cfg.enabled,
        server_name=local_cfg.server_name,
        search_first=local_cfg.search_first,
        auto_capture_candidates=local_cfg.auto_capture_candidates,
        max_search_results=local_cfg.max_search_results,
        min_query_length=local_cfg.min_query_length,
        max_candidate_chars=local_cfg.max_candidate_chars,
        max_context_chars=local_cfg.max_context_chars,
        enable_bootstrap_recall=local_cfg.enable_bootstrap_recall,
    )

    return [LocalMemoryHook(memory_config, tools)]
