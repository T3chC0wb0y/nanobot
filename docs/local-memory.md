# Local memory

Nanobot can use a dedicated MCP server named `local_memory` to search durable memory before a model turn and capture candidate memories after a final response.

## Intended use

Use local memory narrowly:
- prefer Graphify first for codebase/repository questions
- use local memory for reusable procedures, patterns, environment facts, and reviewed decisions
- use live Atera / Microsoft router tools for current external state
- capture candidates first; promote only after Bob review

## Configuration

Example `~/.nanobot/config.json` snippet:

```json
{
  "tools": {
    "local_memory": {
      "enabled": true,
      "server_name": "local_memory",
      "search_first": true,
      "auto_capture_candidates": false,
      "max_search_results": 3,
      "min_query_length": 12,
      "max_candidate_chars": 1200
    },
    "mcpServers": {
      "local_memory": {
        "command": "/home/bjohnson/nanobot/.venv/bin/python",
        "args": [
          "-m",
          "nanobot_local_memory.mcp_stdio"
        ],
        "cwd": "/home/bjohnson/services/local-memory/extensions/local-memory"
      }
    }
  }
}
```

## Runtime behavior

When enabled:
1. before an iteration, Nanobot may search local memory using the current user request
2. matching results are injected as compact context for the model
3. after a final response, Nanobot may build a candidate memory record from the exchange
4. candidate memories stay candidates until explicitly promoted

## Notes

- the MCP server exposes `memory.search`, `memory.capture_candidate`, `memory.promote`, `memory.get`, `memory.list_recent`, and `memory.deprecate`
- searches currently include candidate memories as well as promoted memories
- capture only sends candidate records; it does not auto-promote
