from __future__ import annotations

import argparse
import json
from pathlib import Path

from .storage import SQLiteMemoryStore, default_database_path


def print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Nanobot local memory utility")
    parser.add_argument("--db", type=Path, default=default_database_path())
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="initialize the database")

    search_parser = subparsers.add_parser("search", help="search promoted memory")
    search_parser.add_argument("query")
    search_parser.add_argument("--include-candidates", action="store_true")
    search_parser.add_argument("--limit", type=int, default=8)

    recent_parser = subparsers.add_parser("recent", help="list recent records")
    recent_parser.add_argument("--status")
    recent_parser.add_argument("--limit", type=int, default=10)

    args = parser.parse_args()
    store = SQLiteMemoryStore(args.db)

    if args.command == "init":
        print_json({"database": str(store.database_path), "ok": True})
        return

    if args.command == "search":
        print_json(store.search(args.query, include_candidates=args.include_candidates, limit=args.limit))
        return

    if args.command == "recent":
        print_json([record.to_dict() for record in store.list_recent(status=args.status, limit=args.limit)])
        return

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
