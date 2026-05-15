"""Helpers for lightweight local-memory read/write integration.

This module is intentionally small and bolt-on. It does not replace Nanobot's
workspace memory files. It only talks to a configured local-memory MCP server
and returns compact supplemental recall/candidate-capture requests.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from nanobot.agent.tools.registry import ToolRegistry


_LOCAL_MEMORY_SERVER_NAME = "local_memory"
_DEFAULT_TRACE_PATH = Path("~/.nanobot/logs/memory-recall-trace.jsonl").expanduser()
_RISKY_COMMAND_PATTERN = re.compile(
    r"\b(?:killall|pkill|kill|systemctl)\b|restart(?:-by-agent\.sh)?|\bservice\s+(?:start|stop|restart)\b|terminate\s+process|process\s+termination",
    re.IGNORECASE,
)
_NANOBOT_TARGET_PATTERN = re.compile(
    r"\b(?:nanobot|gateway|agent|listener|local-memory|local_memory|mcp)\b",
    re.IGNORECASE,
)
_EXPLICIT_EMERGENCY_PATTERN = re.compile(
    r"(?:\bbob(?:\s+has)?\s+(?:explicitly\s+)?)?(?:approved|approves|approve)\s+(?:an?\s+)?emergency\s+(?:kill|termination|stop|restart)|\bemergency\s+(?:kill|termination|stop|restart)\s+(?:approved|approves|approve)d?\s+by\s+bob\b|\bbob\b.*\bemergency\b.*\b(?:kill|termination|stop|restart)\b.*\b(?:approved|approves|approve)\b|\b(?:approved|approves|approve)\b.*\bbob\b.*\bemergency\b.*\b(?:kill|termination|stop|restart)\b",
    re.IGNORECASE,
)

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

_MEANINGFUL_WORK_KEYWORDS = (
    "implement",
    "patch",
    "change",
    "edit",
    "modify",
    "update",
    "fix",
    "debug",
    "troubleshoot",
    "investigate",
    "analyze",
    "service",
    "restart",
    "deploy",
    "release",
    "admin",
    "runtime",
    "repo",
    "git",
    "branch",
    "commit",
    "merge",
    "rebase",
    "test",
)

_GUIDANCE_TYPES = ("procedure", "policy", "preference")


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
    trace_path: Path = _DEFAULT_TRACE_PATH


@dataclass(slots=True)
class LocalMemoryInjection:
    heading: str
    content: str
    memory_ids: list[str] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    recall_query: str = ""
    filters: dict[str, Any] = field(default_factory=dict)


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


@dataclass(slots=True)
class RecallDecision:
    should_recall: bool
    reason: str
    query: str
    filters: dict[str, Any] = field(default_factory=dict)
    risky: bool = False
    evidence_only: bool = False


class RiskyActionBlockedError(RuntimeError):
    """Raised when a risky local action lacks approved memory guidance."""


def has_local_memory_server(tool_registry: ToolRegistry, server_name: str = _LOCAL_MEMORY_SERVER_NAME) -> bool:
    return (
        tool_registry.has(f"mcp_{server_name}_memory_build_context")
        or tool_registry.has(f"mcp_{server_name}_memory_search")
    )


def should_search_local_memory(user_text: str, cfg: LocalMemoryConfig) -> bool:
    return classify_recall_need(user_text, cfg).should_recall


def classify_recall_need(user_text: str, cfg: LocalMemoryConfig) -> RecallDecision:
    text = (user_text or "").strip()
    lowered = text.lower()
    if not cfg.enabled or not cfg.search_first:
        return RecallDecision(False, "disabled", text)
    if not text:
        return RecallDecision(False, "empty", text)
    if is_risky_local_action(text):
        return RecallDecision(
            True,
            "risky_local_action",
            _build_context_query(text, "operations"),
            filters=_recall_filters("operations"),
            risky=True,
        )
    query_kind = _classify_memory_query(text)
    if query_kind is not None:
        return RecallDecision(
            True,
            f"classified:{query_kind}",
            _build_context_query(text, query_kind),
            filters=_recall_filters(query_kind),
        )
    if len(lowered) >= cfg.min_query_length and _looks_like_meaningful_work(lowered):
        return RecallDecision(
            True,
            "meaningful_work",
            _build_context_query(text, "project"),
            filters=_recall_filters("project"),
        )
    return RecallDecision(False, "not_meaningful", text)


async def search_local_memory(
    tool_registry: ToolRegistry,
    user_text: str,
    cfg: LocalMemoryConfig,
) -> LocalMemoryInjection | None:
    decision = classify_recall_need(user_text, cfg)
    if not decision.should_recall:
        return None
    build_tool_name = f"mcp_{cfg.server_name}_memory_build_context"
    search_tool_name = f"mcp_{cfg.server_name}_memory_search"

    if tool_registry.has(build_tool_name):
        params = {
            "query": decision.query,
            "include_candidates": False,
            "limit": max(1, cfg.max_search_results),
            "max_chars": max(200, cfg.max_context_chars),
            **decision.filters,
        }
        try:
            result = await tool_registry.execute(build_tool_name, params)
        except Exception:
            logger.exception("Local memory context build failed")
        else:
            rendered = _render_context_result(result)
            records = _extract_records(result)
            if rendered:
                return LocalMemoryInjection(
                    "Supplemental local-memory recall",
                    rendered,
                    memory_ids=_extract_memory_ids(records),
                    records=records,
                    recall_query=decision.query,
                    filters=dict(decision.filters),
                )

    if not tool_registry.has(search_tool_name):
        return None

    params = {
        "query": decision.query,
        "include_candidates": False,
        "limit": max(1, cfg.max_search_results),
        **decision.filters,
    }
    try:
        result = await tool_registry.execute(search_tool_name, params)
    except Exception:
        logger.exception("Local memory search failed")
        return None

    rendered = _render_search_result(result)
    if not rendered:
        return None
    records = _extract_records(result)
    return LocalMemoryInjection(
        "Supplemental local-memory recall",
        rendered,
        memory_ids=_extract_memory_ids(records),
        records=records,
        recall_query=decision.query,
        filters=dict(decision.filters),
    )


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


def build_capture_request(
    user_text: str,
    assistant_text: str,
    cfg: LocalMemoryConfig,
) -> LocalMemoryCaptureRequest | None:
    if not should_capture_candidate(user_text, assistant_text, cfg):
        return None
    clean = _strip_markdown(assistant_text).strip()
    if not clean:
        return None
    if len(clean) > cfg.max_candidate_chars:
        clean = clean[: cfg.max_candidate_chars].rstrip() + "..."
    return LocalMemoryCaptureRequest(
        type=_derive_type(user_text, clean),
        domain=_derive_domain(user_text, clean),
        title=_derive_title(user_text, clean),
        summary=_first_sentence(clean),
        content=clean,
        tags=_derive_tags(user_text, clean),
    )


async def capture_candidate(
    tool_registry: ToolRegistry,
    request: LocalMemoryCaptureRequest,
    cfg: LocalMemoryConfig,
) -> dict[str, Any] | None:
    tool_name = f"mcp_{cfg.server_name}_memory_capture_candidate"
    if not tool_registry.has(tool_name):
        return None
    payload = {
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
        result = await tool_registry.execute(tool_name, payload)
    except Exception:
        logger.exception("Local memory candidate capture failed")
        return None
    return _coerce_dict(result)


def is_risky_local_action(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    if not _targets_nanobot_stack(lowered):
        return False
    if "refresh" in lowered:
        return True
    return bool(_RISKY_COMMAND_PATTERN.search(lowered))


def has_explicit_bob_emergency_approval(text: str) -> bool:
    return bool(_EXPLICIT_EMERGENCY_PATTERN.search((text or "").strip()))


def ensure_risky_action_allowed(user_text: str, recall: LocalMemoryInjection | None) -> None:
    if not is_risky_local_action(user_text):
        return
    lowered = user_text.lower()
    if _is_direct_termination_command(lowered):
        if has_explicit_bob_emergency_approval(user_text):
            return
        raise RiskyActionBlockedError(
            "Direct kill/pkill/killall/process termination for Nanobot, gateway, agent, listener, local-memory, or MCP is blocked without Bob's explicit emergency termination approval."
        )
    if _is_raw_systemctl_stop_or_restart(lowered):
        if has_explicit_bob_emergency_approval(user_text):
            return
        guidance_records = [record for record in (recall.records if recall else []) if _is_guidance_record(record)]
        if guidance_records and any(
            marker in (recall.content or "").lower()
            for marker in ("restart-by-agent.sh", "approved helper", "safe helper")
        ):
            return
        raise RiskyActionBlockedError(
            "Raw systemctl stop/restart for Nanobot, gateway, agent, listener, local-memory, or MCP is blocked unless promoted memory provides an approved safe helper procedure or Bob explicitly approves emergency termination."
        )


def write_recall_trace(
    cfg: LocalMemoryConfig,
    *,
    task_summary: str,
    decision: RecallDecision,
    recall: LocalMemoryInjection | None,
    used_memory_ids: list[str] | None = None,
    ignored: list[dict[str, str]] | None = None,
) -> None:
    if not decision.should_recall:
        return
    payload = {
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "task_label": _sanitize_task_label(task_summary, decision),
        "reason": decision.reason,
        "filters": decision.filters,
        "returned_memory_ids": list(recall.memory_ids if recall else []),
        "used_memory_ids": list(used_memory_ids or []),
        "ignored_memory_ids": list(ignored or []),
    }
    path = cfg.trace_path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _coerce_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            data = json.loads(result)
        except Exception:
            return {"value": result}
        return data if isinstance(data, dict) else {"value": data}
    return {"value": result}


def _has_explicit_capture_cue(user_text: str) -> bool:
    text = (user_text or "").lower()
    explicit_cues = (
        "remember this",
        "save this",
        "store this",
        "capture this",
        "add to memory",
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


def _is_bootstrap_recall_query(text: str) -> bool:
    return any(phrase in text for phrase in ("continue", "pick up", "resume", "where were we"))


def _looks_like_meaningful_work(text: str) -> bool:
    return any(keyword in text for keyword in _MEANINGFUL_WORK_KEYWORDS)


def _build_context_query(user_text: str, query_kind: str | None) -> str:
    text = (user_text or "").strip()[:400]
    if query_kind == "preferences":
        return f"user preferences, response style, operating preferences, personalization\n{text}".strip()
    if query_kind == "project":
        return f"active project context, current plan, next steps, workspace state\n{text}".strip()
    if query_kind == "operations":
        return f"operational runbooks, procedures, environment details\n{text}".strip()
    return text


def _recall_filters(query_kind: str | None) -> dict[str, Any]:
    filters: dict[str, Any] = {"types": list(_GUIDANCE_TYPES)}
    if query_kind == "preferences":
        filters["domains"] = ["user", "engineering", "operations", "project"]
    elif query_kind == "project":
        filters["domains"] = ["engineering", "project", "operations", "user"]
    else:
        filters["domains"] = ["operations", "engineering", "nanobot-operation", "project", "user"]
    return filters


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
        for key in ("results", "matches", "items", "records"):
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


def _extract_records(result: Any) -> list[dict[str, Any]]:
    data = result
    if isinstance(result, str):
        try:
            data = json.loads(result)
        except Exception:
            return []
    if isinstance(data, dict):
        for key in ("results", "matches", "items", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _extract_memory_ids(records: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for record in records:
        value = record.get("record_id") or record.get("id")
        if isinstance(value, str) and value and value not in ids:
            ids.append(value)
    return ids


def _is_guidance_record(record: dict[str, Any]) -> bool:
    if str(record.get("status") or "promoted").lower() != "promoted":
        return False
    return str(record.get("type") or "").lower() in _GUIDANCE_TYPES


def _targets_nanobot_stack(text: str) -> bool:
    return bool(_NANOBOT_TARGET_PATTERN.search(text))


def _is_direct_termination_command(text: str) -> bool:
    direct_terms = (
        "killall",
        "pkill",
        "kill ",
        " kill",
        "terminate process",
        "process termination",
        "terminate pid",
        "kill pid",
    )
    return any(term in text for term in direct_terms)


def _is_raw_systemctl_stop_or_restart(text: str) -> bool:
    return bool(re.search(r"\bsystemctl\s+(?:stop|restart)\b", text))


def _sanitize_task_label(task_summary: str, decision: RecallDecision) -> str:
    if decision.risky:
        lowered = (task_summary or "").lower()
        if _is_direct_termination_command(lowered):
            return "protected-stack direct termination"
        if _is_raw_systemctl_stop_or_restart(lowered):
            return "protected-stack raw systemctl stop/restart"
        return "protected-stack risky local action"
    if decision.reason.startswith("classified:"):
        return decision.reason.removeprefix("classified:")
    if decision.reason == "meaningful_work":
        return "meaningful work recall"
    return decision.reason


def _render_match(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if not isinstance(item, dict):
        return str(item).strip() or None
    title = str(item.get("title") or item.get("name") or item.get("record_id") or "memory").strip()
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
