# Local memory

Nanobot can use a dedicated MCP server named `local_memory` to search durable memory before a model turn and capture candidate memories after a final response.

This integration is a bolt-on augmentation to Nanobot's native workspace memory in the 0426 nightly design. It does not replace Nanobot's existing workspace memory files or Dream/consolidation flow.

Nanobot's canonical in-workspace memory remains:
- `USER.md`
- `SOUL.md`
- `memory/MEMORY.md`
- `memory/history.jsonl`
- Dream/consolidation behavior in nightly

Local memory is supplemental. It is intended for cross-session and cross-workspace recall, reviewed durable records, and candidate capture. If the local-memory MCP server is unavailable, Nanobot should continue operating normally with native workspace memory only.

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
2. matching results are injected as supplemental context for the model, subordinate to Nanobot's primary system prompt
3. after a final response, Nanobot may build a candidate memory record from the exchange
4. candidate memories stay candidates until explicitly promoted
5. Nanobot's native workspace memory flow remains unchanged

## Notes

- the MCP server exposes `memory.search`, `memory.capture_candidate`, `memory.promote`, `memory.get`, `memory.list_recent`, and `memory.deprecate`
- searches should be treated as supplemental recall, not canonical workspace memory
- capture only sends candidate records; it does not auto-promote
- when local memory and current workspace memory differ, prefer current workspace memory for current-workspace behavior unless the user confirms otherwise

## Compact context assembly

When local memory is enabled, the agent should prefer retrieving a compact working-context bundle from promoted local memories before expanding to larger workspace documents. The `memory_build_context` tool exists for this purpose and helps reduce prompt bloat by returning a short, citation-friendly summary block.

## Hook retrieval behavior

The runtime hook should attempt `memory_build_context` first so that first-turn recall is injected as a compact retained-context block. If that tool is unavailable, it may fall back to raw `memory_search` rendering. This keeps prompt growth bounded while preserving graceful degradation.

## Bootstrap and routing heuristics

The local-memory helper now uses lightweight query classification before retrieval:
- preference-style prompts bias toward user preferences and response style
- project/resume prompts bias toward active project context and next steps
- operational prompts bias toward runbooks and environment procedures

On the first iteration, the hook may also bootstrap recall with a synthetic query when no clear user text is available, so the agent can resume with active project context and user preferences.

## Test coverage added

Targeted agent tests now cover:
- build-context-first retrieval on iteration one
- bootstrap recall when user text is absent
- fallback to raw search when compact context is unavailable
- candidate capture after a successful `completed` stop reason
- routing heuristics for preference, project, and operational prompts

