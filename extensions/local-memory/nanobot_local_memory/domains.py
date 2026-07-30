from __future__ import annotations

import re
from collections.abc import Iterable

CANONICAL_DOMAINS = frozenset({"identity", "memory", "operations", "project", "workspace"})
DOMAIN_FILTER_ERROR = "query failed, search with a valid domain or domains"

DOMAIN_ALIASES = {
    "engineering": "project",
    "code": "project",
    "coding": "project",
    "development": "project",
    "repo": "project",
    "repository": "project",
    "nanobot": "project",
    "agentloop": "project",
    "agent-loop": "project",
    "local-memory": "memory",
    "local_memory": "memory",
    "local-memory-mcp": "memory",
    "nanobot-local-memory": "memory",
    "mcp-memory": "memory",
    "memory-service": "memory",
    "ops": "operations",
    "operation": "operations",
    "nanobot-operation": "operations",
    "admin": "operations",
    "administration": "operations",
    "environment": "operations",
    "infra": "operations",
    "infrastructure": "operations",
    "runtime": "operations",
    "personal": "identity",
    "person": "identity",
    "user": "identity",
    "profile": "identity",
    "preference": "identity",
    "preferences": "identity",
    "working-copy": "workspace",
    "working_copy": "workspace",
    "worktree": "workspace",
    "sandbox": "workspace",
}

_UNKNOWN_HINTS = {"", "unknown", "none", "null", "n/a"}
_DOMAIN_FIELD_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def normalize_domain(domain: str | None) -> str | None:
    """Return the canonical fixed-taxonomy domain for a user/tool hint.

    Known legacy names and obvious synonyms are folded into the agreed fixed
    taxonomy. Unknown but syntactically valid values return ``None`` so callers
    can infer an appropriate canonical domain from record text instead of
    preserving an open-ended domain namespace.
    """

    value = re.sub(r"\s+", "-", (domain or "").strip().lower())
    if value in _UNKNOWN_HINTS:
        return None
    value = DOMAIN_ALIASES.get(value, value)
    if value in CANONICAL_DOMAINS:
        return value
    return None


class InvalidDomainFilterError(ValueError):
    """Raised when a search/list domain filter is outside the fixed taxonomy."""

    def __init__(self, invalid_domains: Iterable[str]) -> None:
        values = [value for value in invalid_domains if value]
        detail = f": {', '.join(values)}" if values else ""
        super().__init__(f"{DOMAIN_FILTER_ERROR}{detail}")
        self.invalid_domains = values


def normalize_domain_filters(primary: str | None = None, additional: Iterable[str] | None = None) -> list[str]:
    """Normalize search/list filters while supporting legacy domain aliases.

    Unknown filter values are rejected loudly instead of being dropped or
    converted to an impossible sentinel. A typo or placeholder such as ``.``
    should fail the query with a clear message, not silently produce zero recall.
    """

    values: list[str] = []
    invalid: list[str] = []
    for candidate in [primary, *(list(additional or []))]:
        text = str(candidate or "").strip()
        if not text:
            continue
        normalized = normalize_domain(text)
        if normalized is None:
            invalid.append(text)
            continue
        if normalized not in values:
            values.append(normalized)
    if invalid:
        raise InvalidDomainFilterError(invalid)
    return values


def is_canonical_domain(value: str | None) -> bool:
    return bool(value in CANONICAL_DOMAINS)
