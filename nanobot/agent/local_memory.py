"""Helpers for lightweight local-memory read/write integration.

Designed to be small and cherry-pick friendly on top of nightly.
The integration is MCP-server-name based, so machine-specific command/path
configuration remains in local config rather than tracked code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from nanobot.agent.tools.registry import ToolRegistry


_LOCAL_MEMORY_SERVER_NAME = "local_memory"
_SEARCH_TOOL = f"mcp_{_LOCAL_MEMORY_SERVER_NAME}_memory.search"
_CAPTURE_TOOL = f"mcp_{_LOCAL_MEMORY_SERVER_NAME}_memory.capture_candidate"

_OPERATIONAL_KEYWORDS = (
    "runbook",
    "workflow",
    "service",
    "systemd",
    "listener",
    "port",
    "gateway",
    "proxy",
    "restart",
    "recover",
    "recovery",
    "health",
    "repo",
    "branch",
    "parity",
    "path",
    "config",
    "certificate",
    "exchange",
    "sharepoint",
    "atera",
    "orchestrator",
    "approval",
    "policy",
    "memory",
)


@dataclass(slots=True)
class LocalMemoryConfig:
    enabled: bool = False
    server_name: str = _LOCAL_MEMORY_SERVER_NAME
    search_first: bool = True
    auto_capture_candidates: bool = False
    max_search_results: int = 3
    min_query_length: int = 12
    max_candidate_chars: int = 1200


@dataclass(slots=True)
class LocalMemoryInjection:
    heading: str
    content: str


@dataclass(slots=True)
class LocalMemoryCaptureRequest:
    title: str
    summary: str
    content: str
    tags: list[str] = field(default_factory=list)
    source: str = "conversation"


def has_local_memory_server(tool_registry: ToolRegistry, server_name: str = _LOCAL_MEMORY_SERVER_NAME) -> bool:
    return tool_registry.has(f"mcp_{server_name}_memory.search")


def should_search_local_memory(user_text: str, cfg: LocalMemoryConfig) -> bool:
    text = (user_text or "").strip().lower()
    if not cfg.enabled or not cfg.search_first:
        return False
    if len(text) < cfg.min_query_length:
        return False
    return any(keyword in text for keyword in _OPERATIONAL_KEYWORDS)


async def search_local_memory(
    tool_registry: ToolRegistry,
    user_text: str,
    cfg: LocalMemoryConfig,
) -> LocalMemoryInjection | None:
    tool_name = f"mcp_{cfg.server_name}_memory.search"
    if not tool_registry.has(tool_name):
        return None

    params = {
        "query": user_text[:400],
        "limit": max(1, cfg.max_search_results),
    }
    try:
        result = await tool_registry.execute(tool_name, params)
    except Exception:
        logger.exception("Local memory search failed")
        return None

    rendered = _render_search_result(result)
    if not rendered:
        return None
    return LocalMemoryInjection(
        heading="Relevant local operational memory",
        content=rendered,
    )


def should_capture_candidate(
    user_text: str,
    assistant_text: str | None,
    cfg: LocalMemoryConfig,
) -> bool:
    if not cfg.enabled or not cfg.auto_capture_candidates:
        return False
    if not assistant_text:
        return False
    text = assistant_text.lower()
    if len(assistant_text.strip()) < 80:
        return False
    if any(secret_word in text for secret_word in ("token", "password", "secret", "apikey", "api key")):
        return False
    return any(keyword in user_text.lower() for keyword in _OPERATIONAL_KEYWORDS)


def build_capture_request(
    user_text: str,
    assistant_text: str,
    cfg: LocalMemoryConfig,
) -> LocalMemoryCaptureRequest | None:
    cleaned = _strip_markdown(assistant_text).strip()
    if not cleaned:
        return None
    cleaned = cleaned[: cfg.max_candidate_chars].strip()
    summary = _first_sentence(cleaned, limit=240)
    title = _derive_title(user_text, cleaned)
    tags = _derive_tags(user_text, cleaned)
    return LocalMemoryCaptureRequest(
        title=title,
        summary=summary,
        content=cleaned,
        tags=tags,
    )


async def capture_candidate(
    tool_registry: ToolRegistry,
    request: LocalMemoryCaptureRequest,
    cfg: LocalMemoryConfig,
) -> None:
    tool_name = f"mcp_{cfg.server_name}_memory.capture_candidate"
    if not tool_registry.has(tool_name):
        return
    params = {
        "title": request.title,
        "summary": request.summary,
        "content": request.content,
        "tags": request.tags,
        "source": request.source,
    }
    try:
        await tool_registry.execute(tool_name, params)
    except Exception:
        logger.exception("Local memory candidate capture failed")


def _render_search_result(result: Any) -> str | None:
    if result is None:
        return None
    if isinstance(result, str):
        text = result.strip()
        return text if text else None
    try:
        data = result if isinstance(result, (dict, list)) else json.loads(str(result))
    except Exception:
        return str(result).strip() or None

    if isinstance(data, dict):
        for key in ("results", "matches", "items"):
            if isinstance(data.get(key), list):
                lines = [_render_match(item) for item in data[key][:5]]
                lines = [line for line in lines if line]
                return "\n".join(lines) if lines else None
        return json.dumps(data, ensure_ascii=False)
    if isinstance(data, list):
        lines = [_render_match(item) for item in data[:5]]
        lines = [line for line in lines if line]
        return "\n".join(lines) if lines else None
    return str(data).strip() or None


def _render_match(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if not isinstance(item, dict):
        return str(item).strip() or None
    title = str(item.get("title") or item.get("name") or "memory").strip()
    summary = str(item.get("summary") or item.get("content") or "").strip()
    summary = re.sub(r"\s+", " ", summary)
    if len(summary) > 240:
        summary = summary[:237].rstrip() + "..."
    if not summary:
        return title
    return f"- {title}: {summary}"


def _strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def _first_sentence(text: str, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    match = re.search(r"[.!?]", compact)
    if match and match.end() <= limit:
        return compact[: match.end()].strip()
    return compact[: limit - 3].rstrip() + "..."


def _derive_title(user_text: str, assistant_text: str) -> str:
    base = re.sub(r"\s+", " ", user_text).strip()
    if not base:
        base = assistant_text[:80].strip()
    if len(base) > 80:
        base = base[:77].rstrip() + "..."
    return base


def _derive_tags(user_text: str, assistant_text: str) -> list[str]:
    haystack = f"{user_text} {assistant_text}".lower()
    tags: list[str] = []
    for keyword in _OPERATIONAL_KEYWORDS:
        if keyword in haystack:
            tags.append(keyword.replace(" ", "_"))
    seen: set[str] = set()
    deduped: list[str] = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            deduped.append(tag)
    return deduped[:12]
