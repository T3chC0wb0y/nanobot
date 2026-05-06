from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .schema import MemoryRecord, utc_now_iso


def default_database_path() -> Path:
    configured = os.environ.get("NANOBOT_LOCAL_MEMORY_DB")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".nanobot" / "local-memory" / "memory.sqlite3"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _slugify(value: str, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "memory")[:max_length].strip("-") or "memory"


def build_record_id(record_type: str, title: str, content: str) -> str:
    digest = hashlib.sha256(f"{record_type}\0{title}\0{content}".encode("utf-8")).hexdigest()[:10]
    return f"lm_{_slugify(record_type, 24)}_{_slugify(title, 48)}_{digest}"


class SQLiteMemoryStore:
    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = Path(database_path) if database_path else default_database_path()
        self.database_path = self.database_path.expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL CHECK(status IN ('candidate', 'promoted', 'deprecated')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    promoted_at TEXT,
                    deprecated_at TEXT
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS memory_records_fts USING fts5(
                    id UNINDEXED,
                    type,
                    domain,
                    title,
                    summary,
                    content,
                    tags
                );
                """
            )

    def capture_candidate(
        self,
        *,
        record_type: str,
        domain: str,
        title: str,
        summary: str,
        content: str,
        tags: Iterable[str] | None = None,
        metadata: dict[str, Any] | None = None,
        record_id: str | None = None,
    ) -> MemoryRecord:
        clean_tags = [tag.strip() for tag in tags or [] if tag and tag.strip()]
        now = utc_now_iso()
        record = MemoryRecord(
            id=record_id or build_record_id(record_type, title, content),
            type=record_type.strip(),
            domain=domain.strip(),
            title=title.strip(),
            summary=summary.strip(),
            content=content.strip(),
            tags=clean_tags,
            metadata=metadata or {},
            status="candidate",
            created_at=now,
            updated_at=now,
        )
        record.validate()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_records (
                    id, type, domain, title, summary, content, tags_json, metadata_json,
                    status, created_at, updated_at, promoted_at, deprecated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type=excluded.type,
                    domain=excluded.domain,
                    title=excluded.title,
                    summary=excluded.summary,
                    content=excluded.content,
                    tags_json=excluded.tags_json,
                    metadata_json=excluded.metadata_json,
                    status='candidate',
                    updated_at=excluded.updated_at,
                    promoted_at=NULL,
                    deprecated_at=NULL
                """,
                (
                    record.id,
                    record.type,
                    record.domain,
                    record.title,
                    record.summary,
                    record.content,
                    _json_dumps(record.tags),
                    _json_dumps(record.metadata),
                    record.status,
                    record.created_at,
                    record.updated_at,
                    record.promoted_at,
                    record.deprecated_at,
                ),
            )
            self._replace_fts(conn, record)
        return self.get(record.id) or record

    def promote(self, record_id: str, *, promoted_by: str | None = None, note: str | None = None) -> MemoryRecord:
        record = self.get(record_id)
        if record is None:
            raise KeyError(f"Memory record not found: {record_id}")
        metadata = dict(record.metadata)
        metadata["promoted_by"] = promoted_by or metadata.get("promoted_by") or "unknown"
        if note:
            metadata["promotion_note"] = note
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_records SET status='promoted', updated_at=?, promoted_at=?, deprecated_at=NULL, metadata_json=? WHERE id=?",
                (now, now, _json_dumps(metadata), record_id),
            )
        promoted = self.get(record_id)
        if promoted is None:
            raise KeyError(f"Memory record not found after promote: {record_id}")
        return promoted

    def deprecate(self, record_id: str, *, reason: str, deprecated_by: str | None = None) -> MemoryRecord:
        record = self.get(record_id)
        if record is None:
            raise KeyError(f"Memory record not found: {record_id}")
        metadata = dict(record.metadata)
        metadata["deprecated_by"] = deprecated_by or "unknown"
        metadata["deprecation_reason"] = reason
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_records SET status='deprecated', updated_at=?, deprecated_at=?, metadata_json=? WHERE id=?",
                (now, now, _json_dumps(metadata), record_id),
            )
        deprecated = self.get(record_id)
        if deprecated is None:
            raise KeyError(f"Memory record not found after deprecate: {record_id}")
        return deprecated

    def get(self, record_id: str) -> MemoryRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_records WHERE id=?", (record_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def list_recent(self, *, status: str | None = None, domain: str | None = None, limit: int = 10) -> list[MemoryRecord]:
        limit = max(1, min(int(limit), 100))
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if domain:
            clauses.append("domain=?")
            params.append(domain)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM memory_records {where} ORDER BY updated_at DESC LIMIT ?", (*params, limit)).fetchall()
        return [self._row_to_record(row) for row in rows]

    def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        record_type: str | None = None,
        include_candidates: bool = False,
        include_deprecated: bool = False,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        query = query.strip()
        if not query:
            return []
        statuses = ["promoted"]
        if include_candidates:
            statuses.append("candidate")
        if include_deprecated:
            statuses.append("deprecated")
        try:
            return self._fts_search(query, statuses=statuses, domain=domain, record_type=record_type, limit=limit)
        except sqlite3.OperationalError:
            return self._like_search(query, statuses=statuses, domain=domain, record_type=record_type, limit=limit)

    def _fts_search(self, query: str, *, statuses: list[str], domain: str | None, record_type: str | None, limit: int) -> list[dict[str, Any]]:
        clauses = [f"r.status IN ({','.join('?' for _ in statuses)})", "f.memory_records_fts MATCH ?"]
        params: list[Any] = [*statuses, self._fts_query(query)]
        if domain:
            clauses.append("r.domain=?")
            params.append(domain)
        if record_type:
            clauses.append("r.type=?")
            params.append(record_type)
        sql = f"""
            SELECT r.*, bm25(memory_records_fts) AS score
            FROM memory_records_fts f
            JOIN memory_records r ON r.id = f.id
            WHERE {' AND '.join(clauses)}
            ORDER BY score ASC, r.updated_at DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (*params, limit)).fetchall()
        return [self._search_result(row) for row in rows]

    def _like_search(self, query: str, *, statuses: list[str], domain: str | None, record_type: str | None, limit: int) -> list[dict[str, Any]]:
        like = f"%{query}%"
        clauses = [f"status IN ({','.join('?' for _ in statuses)})", "(title LIKE ? OR summary LIKE ? OR content LIKE ? OR tags_json LIKE ? OR domain LIKE ? OR type LIKE ?)"]
        params: list[Any] = [*statuses, like, like, like, like, like, like]
        if domain:
            clauses.append("domain=?")
            params.append(domain)
        if record_type:
            clauses.append("type=?")
            params.append(record_type)
        sql = f"SELECT *, 0.0 AS score FROM memory_records WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(sql, (*params, limit)).fetchall()
        return [self._search_result(row) for row in rows]

    def _replace_fts(self, conn: sqlite3.Connection, record: MemoryRecord) -> None:
        conn.execute("DELETE FROM memory_records_fts WHERE id=?", (record.id,))
        conn.execute(
            "INSERT INTO memory_records_fts (id, type, domain, title, summary, content, tags) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (record.id, record.type, record.domain, record.title, record.summary, record.content, " ".join(record.tags)),
        )

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = re.findall(r"[\w@.:-]+", query)
        if not tokens:
            return '""'
        return " OR ".join(f'"{token}"' for token in tokens[:16])

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],
            type=row["type"],
            domain=row["domain"],
            title=row["title"],
            summary=row["summary"],
            content=row["content"],
            tags=_json_loads(row["tags_json"], []),
            metadata=_json_loads(row["metadata_json"], {}),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            promoted_at=row["promoted_at"],
            deprecated_at=row["deprecated_at"],
        )

    def _search_result(self, row: sqlite3.Row) -> dict[str, Any]:
        record = self._row_to_record(row).to_dict()
        record["score"] = row["score"] if "score" in row.keys() else None
        return record
