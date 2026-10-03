# Local msadmin read-only connector

This stdio MCP service exposes `gateway_health` and `gateway_capabilities`.
It connects only to `http://127.0.0.1:8790`, sends GET requests to two fixed
paths, rejects redirects, ignores proxy environment variables, and reads the
bearer token internally on each request. It does not change `ssrfWhitelist`
or allow the general web tool to access localhost. It has no execution tools.

## Deployment

The branch is based on the server's `feat/local-memory-nightly-overlay` commit
`5f612d22ed21869ac4bceb718226076e57888cf1`. It changes no Teams channel files.
Preserve the server's uncommitted Teams listener change and test file when
fetching and incorporating this branch. Review `git status --short` first.
The existing editable installation and `httpx`/`mcp` dependencies support it;
no new dependency installation is required.

Add the following named server under the existing `tools.mcpServers` in
`~/.nanobot/config.json`, preserving `local_memory` and other configuration:

```json
"msadmin": {
  "type": "stdio",
  "command": "/home/bjohnson/nanobot/.venv/bin/python",
  "args": ["-m", "nanobot.integrations.msadmin"],
  "cwd": "/home/bjohnson/nanobot",
  "env": {
    "MS_ADMIN_BEARER_TOKEN_FILE": "/home/bjohnson/.config/nanobot-secrets/ms-admin-bearer.token"
  },
  "toolTimeout": 20,
  "enabledTools": ["gateway_health", "gateway_capabilities"]
}
```

Only the token filename belongs in this configuration. Keep the token file
readable only by the service account. Configuration changes and restarting
`nanobot-gateway.service` are deployment steps, not performed by this patch.

After deploying, ask the Teams agent to call
`mcp_msadmin_gateway_health` and `mcp_msadmin_gateway_capabilities`.
Verify their returned results instead of relying on the agent's description
of its configured tools. Missing credentials or HTTP errors return a bounded
error without the upstream response body or authentication header.

The connector deliberately cannot execute gateway actions. Jira writes remain
available through the orchestrator's authenticated `/route` interface and its
existing approval flow. Expanding Nanobot's tools to approved execution is a
separate capability change.

## Validation

```bash
python -m pytest tests/test_msadmin_connector.py -q
```

Tests exercise authentication and token rotation with a mock HTTP transport,
redirect rejection, credential redaction, unsupported paths, unreadable token
files, and real stdio MCP initialization/tool registration. They do not
contact the deployed gateway.
