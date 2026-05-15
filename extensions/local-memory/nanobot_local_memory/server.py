from __future__ import annotations

from typing import Any

from .storage import SQLiteMemoryStore, default_database_path


def _truncate_text(value: str, max_chars: int) -> str:
    text = (value or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _render_record_brief(record: dict[str, Any]) -> str:
    lines: list[str] = []
    title = str(record.get("title") or "").strip()
    if title:
        lines.append(f"- {title}")
    summary = str(record.get("summary") or "").strip()
    if summary:
        lines.append(f"  summary: {summary}")
    domain = str(record.get("domain") or "").strip()
    record_type = str(record.get("type") or "").strip()
    meta_parts = [part for part in (domain, record_type) if part]
    if meta_parts:
        lines.append(f"  scope: {' / '.join(meta_parts)}")
    tags = record.get("tags") or []
    if tags:
        rendered_tags = ", ".join(str(tag) for tag in tags[:8] if str(tag).strip())
        if rendered_tags:
            lines.append(f"  tags: {rendered_tags}")
    content = str(record.get("content") or "").strip()
    if content:
        lines.append(f"  content: {_truncate_text(content, 280)}")
    return "\n".join(lines).strip()


def get_store() -> SQLiteMemoryStore:
    return SQLiteMemoryStore(default_database_path())


def create_mcp_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "Nanobot Local Memory",
        instructions=(
            "Local durable memory for Nanobot. Capture candidate memories first, "
            "promote only after review, and search narrowly for reusable procedures, "
            "project decisions, environment facts, and resolution patterns."
        ),
    )

    @mcp.tool(name="memory_capture_candidate")
    def capture_candidate(
        type: str,
        domain: str,
        title: str,
        summary: str,
        content: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        record_id: str | None = None,
    ) -> dict[str, Any]:
        """Save a proposed durable memory record for later review and promotion."""
        record = get_store().capture_candidate(
            record_type=type,
            domain=domain,
            title=title,
            summary=summary,
            content=content,
            tags=tags,
            metadata=metadata,
            record_id=record_id,
        )
        return {"ok": True, "record": record.to_dict()}

    @mcp.tool(name="memory_promote")
    def promote(record_id: str, promoted_by: str | None = None, note: str | None = None) -> dict[str, Any]:
        """Promote a candidate memory after explicit review."""
        record = get_store().promote(record_id, promoted_by=promoted_by, note=note)
        return {"ok": True, "record": record.to_dict()}

    @mcp.tool(name="memory_search")
    def search(
        query: str,
        domain: str | None = None,
        domains: list[str] | None = None,
        type: str | None = None,
        types: list[str] | None = None,
        include_candidates: bool = False,
        include_deprecated: bool = False,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Search durable local memory. Promoted records are searched by default."""
        results = get_store().search(
            query,
            domain=domain,
            domains=domains,
            record_type=type,
            record_types=types,
            include_candidates=include_candidates,
            include_deprecated=include_deprecated,
            limit=limit,
        )
        return {"ok": True, "count": len(results), "results": results}

    @mcp.tool(name="memory_build_context")
    def build_context(
        query: str,
        domain: str | None = None,
        domains: list[str] | None = None,
        type: str | None = None,
        types: list[str] | None = None,
        include_candidates: bool = False,
        include_deprecated: bool = False,
        limit: int = 8,
        max_chars: int = 2400,
    ) -> dict[str, Any]:
        """Build a compact working-context bundle from relevant local memories."""
        results = get_store().search(
            query,
            domain=domain,
            domains=domains,
            record_type=type,
            record_types=types,
            include_candidates=include_candidates,
            include_deprecated=include_deprecated,
            limit=limit,
        )
        compact = []
        remaining = max(200, int(max_chars))
        for item in results:
            title = str(item.get("title") or "memory").strip()
            summary = str(item.get("summary") or item.get("content") or "").strip()
            summary = " ".join(summary.split())
            line = f"- [{item.get('id')}] {title}: {summary}".strip()
            if len(line) > remaining and compact:
                break
            if len(line) > remaining:
                line = line[: max(0, remaining - 3)].rstrip() + "..."
            compact.append(line)
            remaining -= len(line) + 1
            if remaining <= 0:
                break
        return {
            "ok": True,
            "count": len(results),
            "results": results,
            "context": "\n".join(compact),
        }

    @mcp.tool(name="memory_get")

    def get(record_id: str) -> dict[str, Any]:
        """Fetch one local memory record by id."""
        record = get_store().get(record_id)
        return {"ok": record is not None, "record": record.to_dict() if record else None}

    @mcp.tool(name="memory_list_recent")
    def list_recent(status: str | None = None, domain: str | None = None, limit: int = 10) -> dict[str, Any]:
        """List recently changed local memory records."""
        records = [
            record.to_dict()
            for record in get_store().list_recent(status=status, domain=domain, limit=limit)
        ]
        return {"ok": True, "count": len(records), "records": records}

    @mcp.tool(name="memory_deprecate")
    def deprecate(record_id: str, reason: str, deprecated_by: str | None = None) -> dict[str, Any]:
        """Mark a memory record obsolete without deleting its audit trail."""
        record = get_store().deprecate(record_id, reason=reason, deprecated_by=deprecated_by)
        return {"ok": True, "record": record.to_dict()}

    return mcp
