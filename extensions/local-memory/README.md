# Nanobot Local Memory

Standalone local memory service that Nanobot can call through MCP.

The first implementation is intentionally local-first and dependency-light:

- SQLite storage under `~/.nanobot/local-memory/memory.sqlite3`
- SQLite FTS5 search for low-cost local retrieval
- MCP-compatible stdio server
- Candidate/promoted/deprecated lifecycle so durable memory can require review
- No hosted embedding or vector API calls in the baseline path

This service is meant to complement Nanobot's built-in `MEMORY.md` / `HISTORY.md` flow. It should store reusable operational context, procedures, ticket-resolution patterns, project decisions, and known environment facts. It should not become a full transcript dump.

## Tools

- `memory.capture_candidate` — save a candidate record for later review
- `memory.promote` — mark a candidate as approved durable memory
- `memory.search` — search promoted records by default
- `memory.get` — fetch one record by id
- `memory.list_recent` — list recent records
- `memory.deprecate` — retire an obsolete record without deleting it

## Run locally

```bash
cd ~/nanobot/extensions/local-memory
python -m nanobot_local_memory.mcp_stdio
```

Optional environment variables:

```bash
export NANOBOT_LOCAL_MEMORY_DB="$HOME/.nanobot/local-memory/memory.sqlite3"
```

## Nanobot MCP config sketch

Exact Nanobot config shape may vary by branch, but the service is intended to be launched as a stdio MCP server:

```json
{
  "mcpServers": {
    "local_memory": {
      "command": "python",
      "args": [
        "-m",
        "nanobot_local_memory.mcp_stdio"
      ],
      "env": {
        "NANOBOT_LOCAL_MEMORY_DB": "/home/bjohnson/.nanobot/local-memory/memory.sqlite3",
        "PYTHONPATH": "/home/bjohnson/nanobot/extensions/local-memory"
      }
    }
  }
}
```

## Retrieval policy

Use this service narrowly:

- Code/repo question: ask Graphify first, then read targeted files.
- Known procedure or reusable ticket pattern: search local memory.
- Current ticket/device/user state: call live Atera/Microsoft router.
- New durable lesson: capture candidate first, then promote only after Bob review.

## Record shape

```json
{
  "id": "rm_pattern_shared_mailbox_access",
  "type": "resolution_pattern",
  "domain": "microsoft_365",
  "title": "Shared mailbox access request",
  "summary": "Reusable pattern for validating and applying shared mailbox access.",
  "content": "Steps, checks, approvals, and verification requirements.",
  "tags": ["exchange", "shared-mailbox", "approval-required"],
  "metadata": {
    "source": "bob-reviewed",
    "confidence": "approved"
  }
}
```
