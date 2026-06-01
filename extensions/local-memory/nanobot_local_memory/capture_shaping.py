from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .domains import normalize_domain


_UNKNOWN_HINTS = {"", "unknown", "none", "null", "n/a"}
_FIELD_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_SECRET_PATTERN = re.compile(
    r"\b(?:password|passwd|secret|api[_ -]?key|token|bearer\s+[A-Za-z0-9._~+/-]+|private\s+key)\b",
    re.IGNORECASE,
)
_WHITESPACE_PATTERN = re.compile(r"\s+")
_MARKDOWN_DECORATION_PATTERN = re.compile(r"[`*_>#]")
_PATH_PATTERN = re.compile(r"(?:/[-\w.]+){2,}")


@dataclass(slots=True)
class ShapedCapture:
    record_type: str
    domain: str
    title: str
    summary: str
    content: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def shape_capture_candidate(
    *,
    record_type: str,
    domain: str,
    title: str,
    summary: str,
    content: str,
    tags: Iterable[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ShapedCapture:
    """Normalize and classify a candidate before durable storage.

    Capture shaping is intentionally server-side so Nanobot only needs a thin
    hook and MCP tool calls. The hook may provide hints, but this module owns
    canonical field cleanup, type/domain coercion, tag deduplication, and light
    safety checks for proposed records.
    """

    clean_content = _clean_text(content, max_chars=4000)
    if _SECRET_PATTERN.search(clean_content):
        raise ValueError("Memory content appears to contain a secret and was not captured")

    clean_title = _clean_text(title, max_chars=120) or _derive_title(clean_content)
    clean_summary = _clean_text(summary, max_chars=500) or _derive_summary(clean_content)
    combined = " ".join(part for part in (clean_title, clean_summary, clean_content) if part)

    clean_type = _normalize_type(record_type) or _infer_type(combined)
    clean_domain = normalize_domain(domain) or _infer_domain(combined)
    clean_tags = _shape_tags(tags, combined, clean_type, clean_domain)
    clean_metadata = dict(metadata or {})
    clean_metadata.setdefault("capture_shaped_by", "local-memory-mcp")
    clean_metadata.setdefault("capture_shape_version", 1)

    return ShapedCapture(
        record_type=clean_type,
        domain=clean_domain,
        title=clean_title,
        summary=clean_summary,
        content=clean_content,
        tags=clean_tags,
        metadata=clean_metadata,
    )


def _clean_text(value: str | None, *, max_chars: int) -> str:
    text = _MARKDOWN_DECORATION_PATTERN.sub("", value or "")
    text = _WHITESPACE_PATTERN.sub(" ", text).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def _derive_title(content: str) -> str:
    first = _derive_summary(content)
    return first[:120].strip() or "Untitled memory candidate"


def _derive_summary(content: str) -> str:
    stripped = content.strip()
    if not stripped:
        return "Memory candidate pending review."
    match = re.search(r"(.+?[.!?])(?:\s|$)", stripped)
    if match:
        return match.group(1).strip()[:500]
    return stripped[:500].strip()


def _normalize_type(record_type: str | None) -> str | None:
    value = re.sub(r"\s+", "-", (record_type or "").strip().lower())
    aliases = {
        "procedural": "procedure",
        "runbook": "procedure",
        "decision": "project",
        "preference-note": "preference",
        "prefs": "preference",
    }
    value = aliases.get(value, value)
    if value in _UNKNOWN_HINTS:
        return None
    return value if _FIELD_PATTERN.match(value) else None


def _infer_type(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("prefer", "preference", "usually", "style", "tone", "call me")):
        return "preference"
    if any(token in lowered for token in ("policy", "must", "never", "always", "blocked", "allowed")):
        return "policy"
    if any(token in lowered for token in ("procedure", "runbook", "steps", "workflow", "checklist", "rerun", "restart")):
        return "procedure"
    if any(token in lowered for token in ("project", "repo", "branch", "milestone", "roadmap", "next step")):
        return "project"
    return "fact"


def _infer_domain(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("local-memory", "local memory", "mcp memory", "memory_capture")):
        return "memory"
    if any(token in lowered for token in ("preference", "call me", "my ", "i prefer", "identity")):
        return "identity"
    if any(token in lowered for token in ("workspace", "worktree", "working copy", "checkout", "overlay")):
        return "workspace"
    if any(token in lowered for token in ("nanobot", "agentloop", "agent loop", "listener", "repo", "branch", "commit", "pytest", "code", "implementation")):
        return "project"
    return "operations"


def _shape_tags(tags: Iterable[str] | None, text: str, record_type: str, domain: str) -> list[str]:
    shaped: list[str] = []
    for tag in tags or []:
        normalized = _normalize_tag(tag)
        if normalized and normalized not in shaped:
            shaped.append(normalized)

    lowered = text.lower()
    inferred = [record_type, domain]
    for token in (
        "nanobot",
        "local-memory",
        "mcp",
        "runbook",
        "pytest",
        "git",
        "policy",
        "preference",
        "procedure",
        "overlay",
    ):
        if token in lowered:
            inferred.append(token)
    if _PATH_PATTERN.search(text):
        inferred.append("path")

    for tag in inferred:
        normalized = _normalize_tag(tag)
        if normalized and normalized not in shaped:
            shaped.append(normalized)
    return shaped[:12]


def _normalize_tag(tag: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9_.-]+", "-", (tag or "").strip().lower())
    normalized = normalized.strip("-._")
    if not normalized or len(normalized) > 40:
        return ""
    return normalized
