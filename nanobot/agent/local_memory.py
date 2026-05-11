"""Helpers for lightweight local-memory read/write integration.

This module is intentionally small and bolt-on. It does not replace Nanobot's
workspace memory files. It only talks to a configured local-memory MCP server
and returns compact supplemental recall/candidate-capture requests.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from loguru import logger

from nanobot.agent.tools.registry import ToolRegistry


_LOCAL_MEMORY_SERVER_NAME = "local_memory"

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

_PREFERENCE_KEYWORDS = (
    "prefer",
    "preference",
    "preferred",
    "usually",
    "always",
    "never",
    "style",
    "tone",
    "format",
    "remember",
    "call me",
    "i like",
    "i want",
)

_PROJECT_KEYWORDS = (
    "project",
    "workspace",
    "codebase",
    "repository",
    "repo",
    "roadmap",
    "plan",
    "milestone",
    "next step",
    "todo",
    "task",
    "continue",
)


@dataclass(slots=True)
class LocalMemoryConfig:
    enabled: bool = False
    server_name: str = _LOCAL_MEMORY_SERVER_NAME
    search_first: bool = True
    auto_capture_candidates: bool = False
    capture_mode: Literal["off", "explicit"] = "off"
    max_search_results: int = 3
    min_query_length: int = 12
    max_candidate_chars: int = 1200
    max_context_chars: int = 1600
    enable_bootstrap_recall: bool = True


@dataclass(slots=True)
class LocalMemoryInjection:
    heading: str
    content: str


@dataclass(slots=True)
class LocalMemoryCaptureRequest:
    type: str = "procedure"
    domain: str = "operations"
    title: str = ""
    summary: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    record_id: str | None = None


def has_local_memory_server(tool_registry: ToolRegistry, server_name: str = _LOCAL_MEMORY_SERVER_NAME) -> bool:
    return (
        tool_registry.has(f"mcp_{server_name}_memory_build_context")
        or tool_registry.has(f"mcp_{server_name}_memory_search")
    )


def should_search_local_memory(user_text: str, cfg: LocalMemoryConfig) -> bool:
    text = (user_text or "").strip().lower()
    if not cfg.enabled or not cfg.search_first:
        return False
    if not text:
        return False
    if len(text) < cfg.min_query_length and not _is_bootstrap_recall_query(text):
        return False
    return _classify_memory_query(text) is not None


async def search_local_memory(
    tool_registry: ToolRegistry,
    user_text: str,
    cfg: LocalMemoryConfig,
) -> LocalMemoryInjection | None:
    build_tool_name = f"mcp_{cfg.server_name}_memory_build_context"
    search_tool_name = f"mcp_{cfg.server_name}_memory_search"
    query_kind = _classify_memory_query(user_text)

    if tool_registry.has(build_tool_name):
        params = {
            "query": _build_context_query(user_text, query_kind),
            "include_candidates": False,
            "limit": max(1, cfg.max_search_results),
            "max_chars": max(200, cfg.max_context_chars),
        }
        try:
            result = await tool_registry.execute(build_tool_name, params)
        except Exception:
            logger.exception("Local memory context build failed")
        else:
            rendered = _render_context_result(result)
            if rendered:
                return LocalMemoryInjection("Supplemental local-memory recall", rendered)

    if not tool_registry.has(search_tool_name):
        return None

    params = {
        "query": _build_context_query(user_text, query_kind),
        "include_candidates": False,
        "limit": max(1, cfg.max_search_results),
    }
    try:
        result = await tool_registry.execute(search_tool_name, params)
    except Exception:
        logger.exception("Local memory search failed")
        return None

    rendered = _render_search_result(result)
    if not rendered:
        return None
    return LocalMemoryInjection("Supplemental local-memory recall", rendered)


def should_capture_candidate(user_text: str, assistant_text: str | None, cfg: LocalMemoryConfig) -> bool:
    if not cfg.enabled or cfg.capture_mode != "explicit":
        return False
    if not _has_explicit_capture_cue(user_text):
        return False
    if not assistant_text:
        return False
    if len(assistant_text.strip()) < 80:
        return False
    text = assistant_text.lower()
    if any(secret_word in text for secret_word in ("token", "password", "secret", "apikey", "api key")):
        return False
    return True


def build_capture_request(user_text: str, assistant_text: str, cfg: LocalMemoryConfig) -> LocalMemoryCaptureRequest | None:
    cleaned = _strip_markdown(assistant_text).strip()
    if not cleaned:
        return None
    cleaned = cleaned[: cfg.max_candidate_chars].strip()
    return LocalMemoryCaptureRequest(
        type=_derive_type(user_text, cleaned),
        domain=_derive_domain(user_text, cleaned),
        title=_derive_title(user_text, cleaned),
        summary=_first_sentence(cleaned, limit=240),
        content=cleaned,
        tags=_derive_tags(user_text, cleaned),
        metadata={"source": "conversation", "integration": "nanobot-bolt-on-local-memory"},
    )


async def capture_candidate(tool_registry: ToolRegistry, request: LocalMemoryCaptureRequest, cfg: LocalMemoryConfig) -> None:
    tool_name = f"mcp_{cfg.server_name}_memory_capture_candidate"
    if not tool_registry.has(tool_name):
        return
    params = {
        "type": request.type,
        "domain": request.domain,
        "title": request.title,
        "summary": request.summary,
        "content": request.content,
        "tags": request.tags,
        "metadata": request.metadata,
        "record_id": request.record_id,
    }
    try:
        await tool_registry.execute(tool_name, params)
    except Exception:
        logger.exception("Local memory candidate capture failed")


def _is_bootstrap_recall_query(text: str) -> bool:
    return any(phrase in text for phrase in ("continue", "pick up", "resume", "what next", "where were we"))


def _has_explicit_capture_cue(user_text: str) -> bool:
    text = re.sub(r"\s+", " ", (user_text or "").strip().lower())
    if not text:
        return False
    explicit_cues = (
        "remember this",
        "save this",
        "save this to memory",
        "note this",
        "store this",
    )
    return any(cue in text for cue in explicit_cues)


def _classify_memory_query(user_text: str) -> str | None:
    text = (user_text or "").strip().lower()
    if not text:
        return None
    if any(keyword in text for keyword in _PREFERENCE_KEYWORDS):
        return "preferences"
    if any(keyword in text for keyword in _PROJECT_KEYWORDS):
        return "project"
    if any(keyword in text for keyword in _OPERATIONAL_KEYWORDS):
        return "operations"
    if _is_bootstrap_recall_query(text):
        return "project"
    return None


def _build_context_query(user_text: str, query_kind: str | None) -> str:
    text = (user_text or "").strip()[:400]
    if query_kind == "preferences":
        return f"user preferences, response style, operating preferences, personalization\n{text}".strip()
    if query_kind == "project":
        return f"active project context, current plan, next steps, workspace state\n{text}".strip()
    if query_kind == "operations":
        return f"operational runbooks, procedures, environment details\n{text}".strip()
    return text


def _render_context_result(result: Any) -> str | None:
    if result is None:
        return None
    if isinstance(result, str):
        text = result.strip()
        try:
            data = json.loads(text)
        except Exception:
            return text or None
    else:
        data = result
    if isinstance(data, dict):
        context = data.get("context")
        if isinstance(context, str) and context.strip():
            return context.strip()
        return _render_search_result(data)
    return _render_search_result(data)


def _render_search_result(result: Any) -> str | None:
    if result is None:
        return None
    if isinstance(result, str):
        try:
            data = json.loads(result)
        except Exception:
            return result.strip() or None
    else:
        data = result
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
    return f"- {title}: {summary}" if summary else title


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
    base = re.sub(r"\s+", " ", user_text).strip() or assistant_text[:80].strip()
    return base[:77].rstrip() + "..." if len(base) > 80 else base


def _derive_type(user_text: str, assistant_text: str) -> str:
    haystack = f"{user_text} {assistant_text}".lower()
    if any(word in haystack for word in ("policy", "approval", "rule")):
        return "policy"
    if any(word in haystack for word in ("architecture", "design", "decision")):
        return "decision"
    if any(word in haystack for word in ("fact", "host", "path", "port", "url", "workspace")):
        return "fact"
    return "procedure"


def _derive_domain(user_text: str, assistant_text: str) -> str:
    haystack = f"{user_text} {assistant_text}".lower()
    if any(word in haystack for word in ("repo", "branch", "workspace", "git", "nanobot")):
        return "engineering"
    if any(word in haystack for word in ("microsoft", "exchange", "sharepoint", "teams", "atera")):
        return "it-ops"
    return "operations"


def _derive_tags(user_text: str, assistant_text: str) -> list[str]:
    haystack = f"{user_text} {assistant_text}".lower()
    tags: list[str] = []
    for keyword in _OPERATIONAL_KEYWORDS:
        if keyword in haystack:
            tag = keyword.replace(" ", "_")
            if tag not in tags:
                tags.append(tag)
    return tags[:12]
