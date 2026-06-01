from __future__ import annotations

from collections.abc import Iterable

CANONICAL_MEMORY_DOMAINS: tuple[str, ...] = (
    "identity",
    "memory",
    "operations",
    "project",
    "workspace",
)

CANONICAL_MEMORY_DOMAIN_SET: frozenset[str] = frozenset(CANONICAL_MEMORY_DOMAINS)

DOMAIN_ALIASES: dict[str, str] = {
    "engineering": "project",
    "m365": "operations",
    "microsoft-365": "operations",
    "microsoft_365": "operations",
    "nanobot": "project",
    "personal": "identity",
    "profile": "identity",
    "repo": "project",
    "repository": "project",
    "runbook": "workspace",
    "workspace-docs": "workspace",
    "workspace_docs": "workspace",
}


def normalize_domain(domain: str) -> str:
    """Return the canonical fixed-taxonomy domain for a user supplied domain."""
    value = (domain or "").strip().lower().replace(" ", "_")
    if not value:
        raise ValueError("Memory domain is required")
    return DOMAIN_ALIASES.get(value, value)


def validate_domain(domain: str) -> str:
    """Normalize and validate a memory domain against the fixed taxonomy."""
    normalized = normalize_domain(domain)
    if normalized not in CANONICAL_MEMORY_DOMAIN_SET:
        allowed = ", ".join(CANONICAL_MEMORY_DOMAINS)
        raise ValueError(f"Invalid memory domain: {domain!r}. Expected one of: {allowed}")
    return normalized


def normalize_domains(domains: Iterable[str] | None) -> list[str]:
    """Normalize a list of domain filters, preserving order and removing duplicates."""
    normalized: list[str] = []
    seen: set[str] = set()
    for domain in domains or []:
        value = validate_domain(domain)
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized
