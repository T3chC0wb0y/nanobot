"""Read-only stdio MCP bridge to the explicitly trusted local msadmin service.

This is a separate service connector, not a general-purpose web-fetch tool.
The destination and methods are fixed; no SSRF whitelist is changed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "http://127.0.0.1:8790"
ENDPOINTS = {"health": "/healthz", "capabilities": "/capabilities"}


class GatewayReader:
    def __init__(self, token_file: Path, *, transport: httpx.AsyncBaseTransport | None = None):
        self.token_file = token_file
        self.transport = transport

    async def read(self, operation: str) -> dict[str, Any]:
        if operation not in ENDPOINTS:
            return {"ok": False, "error": "Unsupported read-only operation"}
        try:
            token = self.token_file.expanduser().read_text(encoding="utf-8").strip()
            if not token or "\n" in token or "\r" in token:
                return {"ok": False, "error": "Invalid gateway token file"}
        except (OSError, UnicodeError):
            return {"ok": False, "error": "Gateway token file is not readable"}
        try:
            async with httpx.AsyncClient(
                transport=self.transport, trust_env=False, follow_redirects=False, timeout=10,
            ) as client:
                response = await client.get(
                    BASE_URL + ENDPOINTS[operation],
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
            if response.status_code != 200:
                return {"ok": False, "http_status": response.status_code,
                        "error": "Gateway request failed; redirects are prohibited"}
            # Do not return an upstream body verbatim: an error or proxy could echo credentials.
            data = response.json()
            if not isinstance(data, dict):
                return {"ok": False, "error": "Invalid gateway response"}
            if operation == "health":
                allowed = ("ok", "service", "version", "router_enabled", "resolution_memory_enabled",
                           "exchange_configured", "writes_enabled", "default_dry_run")
                result = {k: v for k, v in data.items() if k in allowed}
            else:
                result = {"ok": data.get("ok", False), "capabilities": data.get("capabilities", {})}
            # Redact even unexpected credential echoes nested in capability descriptions.
            return _redact(result, token)
        except (httpx.HTTPError, ValueError):
            return {"ok": False, "error": "Gateway connection or response failed"}


def _redact(value: Any, token: str) -> Any:
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


def main() -> None:
    from mcp.server.fastmcp import FastMCP

    token_path = os.environ.get("MS_ADMIN_BEARER_TOKEN_FILE", "").strip()
    if not token_path:
        raise SystemExit("MS_ADMIN_BEARER_TOKEN_FILE must reference the gateway token file")
    reader = GatewayReader(Path(token_path))
    server = FastMCP("msadmin-readonly")

    @server.tool()
    async def gateway_health() -> dict[str, Any]:
        """Read authenticated local msadmin health; no changes or restarts."""
        return await reader.read("health")

    @server.tool()
    async def gateway_capabilities() -> dict[str, Any]:
        """Read authenticated msadmin capabilities; no actions are executed."""
        return await reader.read("capabilities")

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
