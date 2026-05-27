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
_EXACT_PATH_PATTERN = re.compile(r"(?:/[\w.\-~]+)+")
_RECORD_ID_PATTERN = re.compile(r"\blm_[A-Za-z0-9_.\-]+\b")

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
_SOURCE_TYPE_VALUES = (
    "mcp",
    "runbook",
    "code",
    "live",
    "user_md",
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


@dataclass(slots=True)
class AdaptiveSourceDecision:
    source_type: Literal["mcp", "runbook", "code", "live", "user_md"]
    reason: str
    pointer_only_mcp: bool = False
    duplicate_search_required: bool = False
    duplicate_search_terms: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvidenceNeed:
    primary_source: Literal["mcp", "runbook", "code", "live", "user_md"]
    reason: str
    needs_orientation: bool = False
    needs_current_verification: bool = False
    needs_implementation_proof: bool = False
    needs_procedure_doc: bool = False


class RiskyActionBlockedError(RuntimeError):
    """Raised when a risky local action lacks approved memory guidance."""


class AdaptiveSourceNegotiationError(RuntimeError):
    """Raised when the authoritative source check is missing or incomplete."""


class IncompleteAuthoritativeSearchError(AdaptiveSourceNegotiationError):
    """Raised when required evidence has not been checked before proceeding."""


class DuplicateMemorySearchRequiredError(AdaptiveSourceNegotiationError):
    """Raised when a memory write/promotion lacks the required duplicate search."""


class MemoryCreationBlockedError(AdaptiveSourceNegotiationError):
    """Raised when a memory write/promotion is blocked by the ASN gate."""


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
    evidence = infer_evidence_need(text)
    query_kind = _classify_memory_query(text)
    if evidence.primary_source == "mcp" or evidence.needs_orientation:
        recall_kind = _recall_kind_for_evidence(text, evidence, query_kind)
        if query_kind is not None or evidence.needs_orientation:
            return RecallDecision(
                True,
                f"evidence:{evidence.reason}",
                _build_context_query(text, recall_kind),
                filters=_recall_filters(recall_kind),
            )
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


def classify_adaptive_source_need(user_text: str) -> AdaptiveSourceDecision:
    text = (user_text or "").strip()
    lowered = text.lower()
    if not text:
        return AdaptiveSourceDecision("mcp", "empty")
    if _looks_like_memory_write_request(lowered):
        return AdaptiveSourceDecision(
            "mcp",
            "memory_write",
            duplicate_search_required=True,
            duplicate_search_terms=_build_duplicate_search_terms(text),
        )

    evidence = infer_evidence_need(text)
    return AdaptiveSourceDecision(
        evidence.primary_source,
        evidence.reason,
        pointer_only_mcp=evidence.needs_orientation and evidence.primary_source == "runbook",
    )


def infer_evidence_need(user_text: str) -> EvidenceNeed:
    """Infer the evidence class required to support a request.

    This deliberately classifies the kind of proof needed instead of matching
    one-off requests.  MCP is the orientation layer for stable references,
    canonical pointers, preferences, and prior decisions; proving sources are
    selected only when the request depends on current runtime state, current
    implementation, maintained procedure text, or stable USER.md identity.
    """
    text = (user_text or "").strip()
    lowered = text.lower()
    if not text:
        return EvidenceNeed("mcp", "empty")

    if _needs_user_profile_evidence(lowered):
        return EvidenceNeed("user_md", "stable_identity_preferences")
    if _needs_live_state_evidence(lowered):
        return EvidenceNeed("live", "current_runtime_live_state", needs_current_verification=True)
    if _needs_code_evidence(lowered):
        return EvidenceNeed("code", "current_implementation", needs_implementation_proof=True)
    if _needs_stable_reference_orientation(lowered):
        return EvidenceNeed("mcp", "stable_reference_orientation", needs_orientation=True)
    if _needs_maintained_procedure_evidence(lowered):
        return EvidenceNeed("runbook", "maintained_procedure", needs_orientation=True, needs_procedure_doc=True)
    return EvidenceNeed("mcp", "continuity_orientation")


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


async def run_duplicate_memory_search(
    tool_registry: ToolRegistry,
    cfg: LocalMemoryConfig,
    *,
    text: str,
    record_id: str | None = None,
    title: str | None = None,
    exact_phrase: str | None = None,
    path: str | None = None,
    aliases: list[str] | None = None,
    domain: str | None = None,
    source_type: str | None = None,
) -> dict[str, Any]:
    search_tool_name = f"mcp_{cfg.server_name}_memory_search"
    if not tool_registry.has(search_tool_name):
        raise DuplicateMemorySearchRequiredError("search incomplete")
    broad_query = title or exact_phrase or path or text.strip() or "memory"
    normalized_aliases = [alias.strip() for alias in (aliases or []) if alias and alias.strip()]
    seen: set[tuple[str, str | None, str | None]] = set()
    search_steps: list[dict[str, Any]] = []

    async def _do_search(query: str, *, type_filter: str | None = None, domain_filter: str | None = None) -> None:
        normalized_query = (query or "").strip()
        if not normalized_query:
            return
        key = (normalized_query.lower(), type_filter, domain_filter)
        if key in seen:
            return
        seen.add(key)
        params: dict[str, Any] = {
            "query": normalized_query,
            "include_candidates": False,
            "include_deprecated": False,
            "limit": max(5, cfg.max_search_results),
        }
        if type_filter:
            params["type"] = type_filter
        if domain_filter:
            params["domain"] = domain_filter
        result = await tool_registry.execute(search_tool_name, params)
        step: dict[str, Any] = {"query": normalized_query, "type": type_filter, "domain": domain_filter, "result": result}
        if type_filter or domain_filter:
            step["source_classification"] = {"type": type_filter, "domain": domain_filter}
        search_steps.append(step)

    exact_id = (record_id or "").strip()
    exact_title = (title or "").strip()
    exact_text = (exact_phrase or "").strip() or (path or "").strip()
    concept_query = broad_query
    if exact_id:
        await _do_search(exact_id)
    if exact_title:
        await _do_search(exact_title)
    if exact_text:
        await _do_search(exact_text)
    await _do_search(concept_query)
    for alias in normalized_aliases:
        await _do_search(alias)
    type_filter = source_type if source_type else None
    domain_filter = domain if domain else None
    await _do_search(concept_query, type_filter=type_filter, domain_filter=domain_filter)

    return {
        "completed": True,
        "queries": [step["query"] for step in search_steps],
        "steps": search_steps,
    }


def ensure_duplicate_memory_search_completed(metadata: dict[str, Any]) -> None:
    duplicate = metadata.get("adaptive_source_duplicate_search")
    if not isinstance(duplicate, dict) or duplicate.get("completed") is not True:
        raise DuplicateMemorySearchRequiredError("search incomplete")
    executed_queries = duplicate.get("queries")
    if not isinstance(executed_queries, list) or len(executed_queries) < 4:
        raise DuplicateMemorySearchRequiredError("search incomplete")


def find_duplicate_memory_blocker(metadata: dict[str, Any]) -> dict[str, Any] | None:
    duplicate = metadata.get("adaptive_source_duplicate_search")
    if not isinstance(duplicate, dict):
        return None
    steps = duplicate.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict):
            continue
        result = step.get("result")
        if not isinstance(result, dict):
            continue
        records = result.get("results")
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            status = str(record.get("status") or "").strip().lower()
            canonical = record.get("canonical") is True or record.get("is_canonical") is True
            if status == "promoted" or canonical:
                return {
                    "record": record,
                    "step": step,
                    "reason": "duplicate existing canonical memory",
                }
    return None


def ensure_memory_write_allowed(metadata: dict[str, Any]) -> None:
    try:
        ensure_duplicate_memory_search_completed(metadata)
    except DuplicateMemorySearchRequiredError as exc:
        raise MemoryCreationBlockedError(str(exc)) from exc
    blocker = find_duplicate_memory_blocker(metadata)
    if blocker is not None:
        raise MemoryCreationBlockedError("search incomplete: duplicate existing canonical memory")


def ensure_authoritative_source_checked(metadata: dict[str, Any], decision: AdaptiveSourceDecision) -> None:
    checks = metadata.get("adaptive_source_checks")
    if not isinstance(checks, dict):
        raise IncompleteAuthoritativeSearchError("search incomplete")
    if decision.source_type == "runbook":
        if checks.get("runbook") is not True:
            raise IncompleteAuthoritativeSearchError("search incomplete")
    elif decision.source_type == "code":
        if checks.get("code") is not True:
            raise IncompleteAuthoritativeSearchError("search incomplete")
    elif decision.source_type == "live":
        if checks.get("live") is not True:
            raise IncompleteAuthoritativeSearchError("search incomplete")
    elif decision.source_type == "user_md":
        if checks.get("user_md") is not True:
            raise IncompleteAuthoritativeSearchError("search incomplete")
    elif decision.source_type == "mcp":
        if decision.duplicate_search_required:
            ensure_duplicate_memory_search_completed(metadata)
        elif checks.get("mcp") is not True:
            raise IncompleteAuthoritativeSearchError("search incomplete")


def record_authoritative_source_check(metadata: dict[str, Any], source_type: str, checked: bool = True) -> None:
    if source_type not in _SOURCE_TYPE_VALUES:
        return
    checks = metadata.setdefault("adaptive_source_checks", {})
    if isinstance(checks, dict):
        checks[source_type] = bool(checked)


def record_duplicate_memory_search(metadata: dict[str, Any], result: dict[str, Any]) -> None:
    metadata["adaptive_source_duplicate_search"] = result
    record_authoritative_source_check(metadata, "mcp", True)


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
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if metadata is not None:
        ensure_memory_write_allowed(metadata)
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


def _render_context_result(result: Any) -> str:
    if isinstance(result, dict):
        context = result.get("context")
        if isinstance(context, str):
            return context.strip()
    if isinstance(result, str):
        return result.strip()
    return ""


def _render_search_result(result: Any) -> str:
    if isinstance(result, dict):
        rows = []
        for record in _extract_records(result):
            title = str(record.get("title") or record.get("record_id") or "Untitled").strip()
            summary = str(record.get("summary") or record.get("content") or "").strip()
            line = f"- {title}"
            if summary:
                line += f": {summary}"
            rows.append(line)
        return "\n".join(rows).strip()
    if isinstance(result, list):
        rows = []
        for item in result:
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("record_id") or "Untitled").strip()
                summary = str(item.get("summary") or item.get("content") or "").strip()
                line = f"- {title}"
                if summary:
                    line += f": {summary}"
                rows.append(line)
        return "\n".join(rows).strip()
    if isinstance(result, str):
        return result.strip()
    return ""


def _extract_records(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, dict):
        if isinstance(result.get("results"), list):
            return [item for item in result["results"] if isinstance(item, dict)]
        if isinstance(result.get("records"), list):
            return [item for item in result["records"] if isinstance(item, dict)]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def _extract_memory_ids(records: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for record in records:
        for key in ("record_id", "id"):
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                ids.append(value.strip())
                break
    return ids


def _classify_memory_query(text: str) -> str | None:
    lowered = text.lower()
    if any(keyword in lowered for keyword in _PREFERENCE_KEYWORDS):
        return "preferences"
    if any(keyword in lowered for keyword in _OPERATIONAL_KEYWORDS):
        return "operations"
    if any(keyword in lowered for keyword in _PROJECT_KEYWORDS):
        return "project"
    return None


def _recall_filters(kind: str) -> dict[str, Any]:
    if kind == "preferences":
        return {"domains": ["nanobot", "personal"], "types": ["preference", "policy"]}
    if kind == "operations":
        return {"domains": ["operations", "nanobot"], "types": ["procedure", "policy"]}
    if kind == "project":
        return {"domains": ["project", "nanobot", "operations"], "types": ["project", "procedure", "policy"]}
    return {}


def _build_context_query(text: str, kind: str) -> str:
    clean = " ".join(text.split())
    if kind == "preferences":
        return f"user preferences and stable instructions for: {clean}"
    if kind == "operations":
        return f"operational guidance, procedures, canonical pointers, and policies for: {clean}"
    if kind == "project":
        return f"active project context, prior decisions, next steps, and constraints for: {clean}"
    return clean


def _looks_like_meaningful_work(lowered: str) -> bool:
    return any(keyword in lowered for keyword in _MEANINGFUL_WORK_KEYWORDS)


def _targets_nanobot_stack(lowered: str) -> bool:
    return bool(_NANOBOT_TARGET_PATTERN.search(lowered))


def _is_direct_termination_command(lowered: str) -> bool:
    return bool(re.search(r"\b(?:killall|pkill|kill|terminate\s+process|process\s+termination)\b", lowered, re.IGNORECASE))


def _is_raw_systemctl_stop_or_restart(lowered: str) -> bool:
    return bool(re.search(r"\bsystemctl\s+(?:stop|restart)\b", lowered, re.IGNORECASE))


def _is_guidance_record(record: dict[str, Any]) -> bool:
    record_type = str(record.get("type") or "").strip().lower()
    status = str(record.get("status") or "").strip().lower()
    return record_type in _GUIDANCE_TYPES and status == "promoted"


def _sanitize_task_label(task_summary: str, decision: RecallDecision) -> str:
    if decision.risky:
        return "risky action recall"
    if decision.reason.startswith("classified:"):
        return f"{decision.reason.split(':', 1)[1]} recall"
    if decision.reason == "meaningful_work":
        return "meaningful work recall"
    return "local memory recall"


def _has_explicit_capture_cue(user_text: str) -> bool:
    lowered = (user_text or "").lower()
    return any(cue in lowered for cue in ("remember this", "save this", "store this", "capture this"))


def _strip_markdown(text: str) -> str:
    return re.sub(r"[`*_>#]", "", text or "")


def _first_sentence(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return ""
    match = re.search(r"(.+?[.!?])(?:\s|$)", stripped, re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped[:160].strip()


def _derive_type(user_text: str, assistant_text: str) -> str:
    lowered = f"{user_text} {assistant_text}".lower()
    if any(token in lowered for token in ("procedure", "runbook", "steps", "pytest path", "focused tests")):
        return "procedure"
    if "policy" in lowered:
        return "policy"
    if "prefer" in lowered or "preference" in lowered:
        return "preference"
    return "procedure"


def _derive_domain(user_text: str, assistant_text: str) -> str:
    lowered = f"{user_text} {assistant_text}".lower()
    if any(token in lowered for token in ("repo", "git", "code", "project")):
        return "project"
    if any(token in lowered for token in ("nanobot", "mcp", "runbook", "service", "workflow")):
        return "nanobot"
    return "operations"


def _derive_title(user_text: str, assistant_text: str) -> str:
    source = (user_text or "").strip() or _first_sentence(assistant_text)
    source = re.sub(r"\s+", " ", source)
    return source[:80].strip()


def _derive_tags(user_text: str, assistant_text: str) -> list[str]:
    lowered = f"{user_text} {assistant_text}".lower()
    tags: list[str] = []
    for token in ("nanobot", "mcp", "runbook", "repo", "git", "policy", "preference", "procedure"):
        if token in lowered and token not in tags:
            tags.append(token)
    return tags


def _recall_kind_for_evidence(text: str, evidence: EvidenceNeed, classified: str | None = None) -> str:
    if classified is None:
        classified = _classify_memory_query(text)
    if classified is not None:
        return classified
    lowered = text.lower()
    if evidence.primary_source == "user_md":
        return "preferences"
    if _needs_stable_reference_orientation(lowered) or _needs_maintained_procedure_evidence(lowered):
        return "operations"
    return "project"


def _needs_user_profile_evidence(lowered: str) -> bool:
    return "user.md" in lowered or any(phrase in lowered for phrase in (
        "my preference",
        "my preferences",
        "call me",
        "who am i",
        "stable preference",
        "stable identity",
    ))


def _needs_live_state_evidence(lowered: str) -> bool:
    state_terms = (
        "running",
        "status",
        "health",
        "active process",
        "port open",
        "service up",
        "system state",
        "runtime",
        "live state",
    )
    temporal_terms = ("currently", "right now", "now", "live", "active")
    return any(term in lowered for term in state_terms) and (
        any(term in lowered for term in temporal_terms)
        or any(term in lowered for term in ("status", "health", "running", "service up", "active process"))
    )


def _needs_code_evidence(lowered: str) -> bool:
    implementation_terms = (
        "implement",
        "implementation",
        "function",
        "class",
        "method",
        "in the code",
        "code path",
        "patch",
        "edit file",
        "refactor",
        "test",
        "read the code",
    )
    return any(term in lowered for term in implementation_terms)


def _needs_stable_reference_orientation(lowered: str) -> bool:
    reference_terms = (
        "canonical",
        "pointer",
        "reference",
        "where",
        "location",
        "path",
        "kept",
        "located",
        "find",
        "stored",
        "remembered",
        "prior decision",
        "previous decision",
        "agreed",
    )
    durable_context_terms = (
        "runbook",
        "workflow",
        "procedure",
        "config",
        "repository",
        "repo",
        "branch",
        "service",
        "tooling",
        "operating reference",
        "system reference",
    )
    asks_for_pointer = any(term in lowered for term in reference_terms)
    has_durable_target = any(term in lowered for term in durable_context_terms)
    return asks_for_pointer and has_durable_target


def _needs_maintained_procedure_evidence(lowered: str) -> bool:
    procedure_terms = (
        "documented procedure",
        "maintained procedure",
        "official procedure",
        "runbook procedure",
        "runbook workflow",
        "docs",
        "documentation",
        "playbook",
        "checklist",
        "workflow",
        "procedure",
    )
    return any(term in lowered for term in procedure_terms)


def _looks_like_memory_write_request(lowered: str) -> bool:
    return any(phrase in lowered for phrase in (
        "remember this",
        "save this",
        "store this",
        "capture this",
        "add mcp memory",
        "promote this memory",
        "write memory",
    ))


def _looks_like_user_identity_request(lowered: str) -> bool:
    return "user.md" in lowered or any(phrase in lowered for phrase in (
        "my preference",
        "my preferences",
        "call me",
        "who am i",
        "stable preference",
        "stable identity",
    ))


def _looks_like_live_state_request(lowered: str) -> bool:
    return any(token in lowered for token in (
        "live state",
        "runtime",
        "running",
        "currently",
        "status",
        "health",
        "active process",
        "port open",
        "service up",
        "system state",
    ))


def _looks_like_code_request(lowered: str) -> bool:
    return any(token in lowered for token in (
        "implement",
        "code",
        "function",
        "class",
        "method",
        "current implementation",
        "in the code",
        "patch",
        "edit file",
        "refactor",
        "test",
    ))


def _looks_like_runbook_request(lowered: str) -> bool:
    return any(token in lowered for token in (
        "runbook",
        "documented procedure",
        "docs",
        "documentation",
        "playbook",
        "checklist",
        "workflow",
        "procedure",
    ))


def _build_duplicate_search_terms(text: str) -> list[str]:
    terms: list[str] = []
    record_ids = _RECORD_ID_PATTERN.findall(text)
    for rid in record_ids:
        if rid not in terms:
            terms.append(rid)
    paths = _EXACT_PATH_PATTERN.findall(text)
    for path in paths:
        if path not in terms:
            terms.append(path)
    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
    for pair in quoted:
        candidate = next((part for part in pair if part), "")
        candidate = candidate.strip()
        if candidate and candidate not in terms:
            terms.append(candidate)
    normalized = " ".join(text.split()).strip()
    if normalized and normalized not in terms:
        terms.append(normalized[:160])
    return terms
