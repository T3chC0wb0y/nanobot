import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from nanobot.bus.events import OutboundMessage
from nanobot.channels.msteams import ConversationRef, MSTeamsChannel


class DummyBus:
    def __init__(self):
        self.inbound = []

    async def publish_inbound(self, msg):
        self.inbound.append(msg)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, payload=None, get_payloads=None):
        self.payload = payload or {"access_token": "tok", "expires_in": 3600}
        self.get_payloads = get_payloads or {}
        self.calls = []
        self.get_calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)

    async def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return FakeResponse(self.get_payloads[url])


def make_test_jwk_and_token(app_id: str, service_url: str = "https://smba.trafficmanager.net/amer/"):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    jwk_json = jwt.algorithms.RSAAlgorithm.to_jwk(public_key)
    jwk = json.loads(jwk_json)
    jwk["kid"] = "test-kid"
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "https://api.botframework.com",
            "aud": app_id,
            "iat": now,
            "exp": now + 3600,
            "serviceurl": service_url,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-kid"},
    )
    return jwk, token


@pytest.mark.asyncio
async def test_handle_activity_personal_message_publishes_and_stores_ref(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
        },
        bus,
    )

    activity = {
        "type": "message",
        "id": "activity-1",
        "text": "Hello from Teams",
        "serviceUrl": "https://smba.trafficmanager.net/amer/",
        "conversation": {
            "id": "conv-123",
            "conversationType": "personal",
        },
        "from": {
            "id": "29:user-id",
            "aadObjectId": "aad-user-1",
            "name": "Bob",
        },
        "recipient": {
            "id": "28:bot-id",
            "name": "nanobot",
        },
        "channelData": {
            "tenant": {"id": "tenant-id"},
        },
    }

    await ch._handle_activity(activity)

    assert len(bus.inbound) == 1
    msg = bus.inbound[0]
    assert msg.channel == "msteams"
    assert msg.sender_id == "aad-user-1"
    assert msg.chat_id == "conv-123"
    assert msg.content == "Hello from Teams"
    assert msg.metadata["msteams"]["conversation_id"] == "conv-123"
    assert "conv-123" in ch._conversation_refs

    saved = json.loads((tmp_path / "state" / "msteams_conversations.json").read_text(encoding="utf-8"))
    assert saved["conv-123"]["conversation_id"] == "conv-123"
    assert saved["conv-123"]["tenant_id"] == "tenant-id"


@pytest.mark.asyncio
async def test_handle_activity_ignores_group_messages(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
        },
        bus,
    )

    activity = {
        "type": "message",
        "id": "activity-2",
        "text": "Hello group",
        "serviceUrl": "https://smba.trafficmanager.net/amer/",
        "conversation": {
            "id": "conv-group",
            "conversationType": "channel",
        },
        "from": {
            "id": "29:user-id",
            "aadObjectId": "aad-user-1",
            "name": "Bob",
        },
        "recipient": {
            "id": "28:bot-id",
            "name": "nanobot",
        },
    }

    await ch._handle_activity(activity)

    assert bus.inbound == []
    assert ch._conversation_refs == {}


@pytest.mark.asyncio
async def test_handle_activity_mention_only_uses_default_response(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
        },
        bus,
    )

    activity = {
        "type": "message",
        "id": "activity-3",
        "text": "<at>Nanobot</at>",
        "serviceUrl": "https://smba.trafficmanager.net/amer/",
        "conversation": {
            "id": "conv-empty",
            "conversationType": "personal",
        },
        "from": {
            "id": "29:user-id",
            "aadObjectId": "aad-user-1",
            "name": "Bob",
        },
        "recipient": {
            "id": "28:bot-id",
            "name": "nanobot",
        },
    }

    await ch._handle_activity(activity)

    assert len(bus.inbound) == 1
    assert bus.inbound[0].content == "Hi — what can I help with?"
    assert "conv-empty" in ch._conversation_refs


@pytest.mark.asyncio
async def test_handle_activity_mention_only_ignores_when_response_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
            "mentionOnlyResponse": "   ",
        },
        bus,
    )

    activity = {
        "type": "message",
        "id": "activity-4",
        "text": "<at>Nanobot</at>",
        "serviceUrl": "https://smba.trafficmanager.net/amer/",
        "conversation": {
            "id": "conv-empty-disabled",
            "conversationType": "personal",
        },
        "from": {
            "id": "29:user-id",
            "aadObjectId": "aad-user-1",
            "name": "Bob",
        },
        "recipient": {
            "id": "28:bot-id",
            "name": "nanobot",
        },
    }

    await ch._handle_activity(activity)

    assert bus.inbound == []
    assert ch._conversation_refs == {}


def test_strip_possible_bot_mention_removes_generic_at_tags(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
        },
        bus,
    )

    assert ch._strip_possible_bot_mention("<at>Nanobot</at> hello") == "hello"
    assert ch._strip_possible_bot_mention("hi <at>Some Bot</at> there") == "hi there"


@pytest.mark.asyncio
async def test_validate_request_accepts_valid_bearer_token(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
            "validateInboundAuth": True,
        },
        bus,
    )

    jwk, token = make_test_jwk_and_token("app-id")
    ch._http = FakeHttpClient(
        get_payloads={
            "https://login.botframework.com/v1/.well-known/openidconfiguration": {
                "issuer": "https://api.botframework.com",
                "jwks_uri": "https://login.botframework.com/v1/.well-known/keys",
            },
            "https://login.botframework.com/v1/.well-known/keys": {
                "keys": [jwk],
            },
        }
    )

    ok = await ch._validate_request(
        {"serviceUrl": "https://smba.trafficmanager.net/amer/"},
        f"Bearer {token}",
    )

    assert ok is True


@pytest.mark.asyncio
async def test_validate_request_rejects_missing_bearer_token(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
            "validateInboundAuth": True,
        },
        bus,
    )

    ch._http = FakeHttpClient()
    ok = await ch._validate_request(
        {"serviceUrl": "https://smba.trafficmanager.net/amer/"},
        "",
    )

    assert ok is False


@pytest.mark.asyncio
async def test_validate_request_rejects_service_url_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
            "validateInboundAuth": True,
        },
        bus,
    )

    jwk, token = make_test_jwk_and_token("app-id", service_url="https://smba.trafficmanager.net/emea/")
    ch._http = FakeHttpClient(
        get_payloads={
            "https://login.botframework.com/v1/.well-known/openidconfiguration": {
                "issuer": "https://api.botframework.com",
                "jwks_uri": "https://login.botframework.com/v1/.well-known/keys",
            },
            "https://login.botframework.com/v1/.well-known/keys": {
                "keys": [jwk],
            },
        }
    )

    ok = await ch._validate_request(
        {"serviceUrl": "https://smba.trafficmanager.net/amer/"},
        f"Bearer {token}",
    )

    assert ok is False


@pytest.mark.asyncio
async def test_get_access_token_uses_configured_tenant(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-123",
            "allowFrom": ["*"],
        },
        bus,
    )

    fake_http = FakeHttpClient()
    ch._http = fake_http

    token = await ch._get_access_token()

    assert token == "tok"
    assert len(fake_http.calls) == 1
    url, kwargs = fake_http.calls[0]
    assert url == "https://login.microsoftonline.com/tenant-123/oauth2/v2.0/token"
    assert kwargs["data"]["client_id"] == "app-id"
    assert kwargs["data"]["client_secret"] == "secret"
    assert kwargs["data"]["scope"] == "https://api.botframework.com/.default"


@pytest.mark.asyncio
async def test_send_replies_to_activity_when_reply_in_thread_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
            "replyInThread": True,
        },
        bus,
    )

    fake_http = FakeHttpClient()
    ch._http = fake_http
    ch._token = "tok"
    ch._token_expires_at = 9999999999
    ch._conversation_refs["conv-123"] = ConversationRef(
        service_url="https://smba.trafficmanager.net/amer/",
        conversation_id="conv-123",
        activity_id="activity-1",
    )

    await ch.send(OutboundMessage(channel="msteams", chat_id="conv-123", content="Reply text"))

    assert len(fake_http.calls) == 1
    url, kwargs = fake_http.calls[0]
    assert url == "https://smba.trafficmanager.net/amer/v3/conversations/conv-123/activities/activity-1"
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["json"]["text"] == "Reply text"
    assert kwargs["json"]["replyToId"] == "activity-1"


@pytest.mark.asyncio
async def test_send_posts_to_conversation_when_thread_reply_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
            "replyInThread": False,
        },
        bus,
    )

    fake_http = FakeHttpClient()
    ch._http = fake_http
    ch._token = "tok"
    ch._token_expires_at = 9999999999
    ch._conversation_refs["conv-123"] = ConversationRef(
        service_url="https://smba.trafficmanager.net/amer/",
        conversation_id="conv-123",
        activity_id="activity-1",
    )

    await ch.send(OutboundMessage(channel="msteams", chat_id="conv-123", content="Reply text"))

    assert len(fake_http.calls) == 1
    url, kwargs = fake_http.calls[0]
    assert url == "https://smba.trafficmanager.net/amer/v3/conversations/conv-123/activities"
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["json"]["text"] == "Reply text"
    assert "replyToId" not in kwargs["json"]


@pytest.mark.asyncio
async def test_send_posts_to_conversation_when_thread_reply_enabled_but_no_activity_id(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
            "replyInThread": True,
        },
        bus,
    )

    fake_http = FakeHttpClient()
    ch._http = fake_http
    ch._token = "tok"
    ch._token_expires_at = 9999999999
    ch._conversation_refs["conv-123"] = ConversationRef(
        service_url="https://smba.trafficmanager.net/amer/",
        conversation_id="conv-123",
        activity_id=None,
    )

    await ch.send(OutboundMessage(channel="msteams", chat_id="conv-123", content="Reply text"))

    assert len(fake_http.calls) == 1
    url, kwargs = fake_http.calls[0]
    assert url == "https://smba.trafficmanager.net/amer/v3/conversations/conv-123/activities"
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["json"]["text"] == "Reply text"
    assert "replyToId" not in kwargs["json"]
