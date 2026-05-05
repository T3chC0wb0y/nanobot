from __future__ import annotations

from typing import Any

from .storage import SQLiteMemoryStore, default_database_path


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

    @mcp.tool(name="memory.capture_candidate")
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

    @mcp.tool(name="memory.promote")
    def promote(record_id: str, promoted_by: str = "Bob", note: str | None = None) -> dict[str, Any]:
        """Promote a candidate memory after explicit review."""
        record = get_store().promote(record_id, promoted_by=promoted_by, note=note)
        return {"ok": True, "record": record.to_dict()}

    @mcp.tool(name="memory.search")
    def search(
        query: str,
        domain: str | None = None,
        type: str | None = None,
        include_candidates: bool = False,
        include_deprecated: bool = False,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Search durable local memory. Promoted records are searched by default."""
        results = get_store().search(
            query,
            domain=domain,
            record_type=type,
            include_candidates=include_candidates,
            include_deprecated=include_deprecated,
            limit=limit,
        )
        return {"ok": True, "count": len(results), "results": results}

    @mcp.tool(name="memory.get")
    def get(record_id: str) -> dict[str, Any]:
        """Fetch one local memory record by id."""
        record = get_store().get(record_id)
        return {"ok": record is not None, "record": record.to_dict() if record else None}

    @mcp.tool(name="memory.list_recent")
    def list_recent(status: str | None = None, domain: str | None = None, limit: int = 10) -> dict[str, Any]:
        """List recently changed local memory records."""
        records = [
            record.to_dict()
            for record in get_store().list_recent(status=status, domain=domain, limit=limit)
        ]
        return {"ok": True, "count": len(records), "records": records}

    @mcp.tool(name="memory.deprecate")
    def deprecate(record_id: str, reason: str, deprecated_by: str = "Bob") -> dict[str, Any]:
        """Mark a memory record obsolete without deleting its audit trail."""
        record = get_store().deprecate(record_id, reason=reason, deprecated_by=deprecated_by)
        return {"ok": True, "record": record.to_dict()}

    return mcp
