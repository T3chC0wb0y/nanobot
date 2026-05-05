from __future__ import annotations

import sys

from .server import create_mcp_server


def main() -> None:
    try:
        mcp = create_mcp_server()
    except ModuleNotFoundError as exc:
        if exc.name == "mcp":
            print(
                "The MCP Python SDK is required. Install this service with `uv sync` "
                "from extensions/local-memory or run `uv pip install 'mcp[cli]'`.",
                file=sys.stderr,
            )
            raise SystemExit(2) from exc
        raise
    mcp.run()


if __name__ == "__main__":
    main()
