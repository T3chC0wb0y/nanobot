import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from nanobot.integrations.msadmin import GatewayReader


@pytest.mark.asyncio
async def test_fixed_endpoint_auth_and_token_rotation(tmp_path):
    token = tmp_path / "token"
    token.write_text("secret-one\n")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "service": "msadmin-gateway"})

    reader = GatewayReader(token, transport=httpx.MockTransport(handler))
    assert (await reader.read("health"))["ok"]
    token.write_text("secret-two")
    assert (await reader.read("health"))["ok"]
    assert all(str(r.url) == "http://127.0.0.1:8790/healthz" for r in requests)
    assert [r.headers["authorization"] for r in requests] == ["Bearer secret-one", "Bearer secret-two"]
    assert all(r.method == "GET" for r in requests)


@pytest.mark.asyncio
async def test_redirect_is_not_followed_and_body_is_not_exposed(tmp_path):
    token = tmp_path / "token"
    token.write_text("private-secret")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://other.example"}, text="private-secret")

    result = await GatewayReader(token, transport=httpx.MockTransport(handler)).read("health")
    assert result["http_status"] == 302
    assert len(calls) == 1
    assert "private-secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_capability_secret_echo_is_redacted(tmp_path):
    token = tmp_path / "token"
    token.write_text("private-secret")
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
        "ok": True, "capabilities": {"private-secret": ["Bearer private-secret"]},
    }))
    result = await GatewayReader(token, transport=transport).read("capabilities")
    assert "private-secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_unsupported_operation_and_missing_token_never_connect(tmp_path):
    def handler(_):
        raise AssertionError("No network request expected")

    reader = GatewayReader(tmp_path / "missing", transport=httpx.MockTransport(handler))
    assert not (await reader.read("http://169.254.169.254"))["ok"]
    assert not (await reader.read("health"))["ok"]


@pytest.mark.asyncio
async def test_real_stdio_mcp_registration_and_call(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root = str(Path(__file__).resolve().parents[1])
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "nanobot.integrations.msadmin"],
        env={**os.environ, "PYTHONPATH": root,
             "MS_ADMIN_BEARER_TOKEN_FILE": str(tmp_path / "missing-token")},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {"gateway_health", "gateway_capabilities"}
            response = await session.call_tool("gateway_health", {})
            assert "not readable" in response.content[0].text
