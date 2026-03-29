import base64
from pathlib import Path

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.imessage import (
    IMessageChannel,
    _extract_address,
    _is_photon_kit_url,
    _make_bearer_token,
    _resolve_proxy_url,
)


class DummyBus:
    def __init__(self):
        self.inbound = []

    async def publish_inbound(self, msg):
        self.inbound.append(msg)


class FakeResponse:
    def __init__(self, payload=None, *, is_success=True, status_code=200, content=b""):
        self._payload = payload
        self.is_success = is_success
        self.status_code = status_code
        self.content = content

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self):
        self.calls = []
        self.messages = []
        self.attachments = {}

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url == "/health":
            return FakeResponse({"ok": True})
        if url == "/messages":
            return FakeResponse({"data": self.messages})
        if url.startswith("/attachments/"):
            guid = url.rsplit("/", 1)[-1]
            return FakeResponse({}, content=self.attachments.get(guid, b"file-bytes"))
        return FakeResponse({"data": None})

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return FakeResponse({"data": {"ok": True}})

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse({"data": {"ok": True}})

    async def aclose(self):
        return None


def test_make_bearer_token_encodes_raw_key():
    token = _make_bearer_token("https://server.example", "secret-key")
    assert base64.b64decode(token).decode() == "https://server.example|secret-key"


def test_make_bearer_token_keeps_preencoded_pair():
    raw = base64.b64encode(b"https://server.example|secret-key").decode()
    assert _make_bearer_token("https://other.example", raw) == raw


def test_photon_helpers_detect_and_resolve_proxy():
    kit_url = "https://abc123.imsgd.photon.codes"
    assert _is_photon_kit_url(kit_url) is True
    assert _resolve_proxy_url(kit_url) == "https://imessage-swagger.photon.codes"
    assert _resolve_proxy_url("https://example.com") == "https://example.com"


def test_extract_address_handles_personal_and_group_chat_ids():
    assert _extract_address("iMessage;-;+15551234567") == "+15551234567"
    assert _extract_address("iMessage;+;chat123") == "group:chat123"
    assert _extract_address("plain-chat") == "plain-chat"


@pytest.mark.asyncio
async def test_seed_existing_message_ids_marks_history_seen():
    bus = DummyBus()
    ch = IMessageChannel(
        {
            "enabled": True,
            "serverUrl": "https://server.example",
            "apiKey": "secret",
            "allowFrom": ["*"],
        },
        bus,
    )
    fake_http = FakeHttpClient()
    fake_http.messages = [{"id": "m1"}, {"guid": "m2"}]
    ch._http = fake_http

    await ch._seed_existing_message_ids()

    assert ch._is_seen("m1") is True
    assert ch._is_seen("m2") is True


@pytest.mark.asyncio
async def test_send_posts_text_and_media_and_typing_calls(tmp_path):
    bus = DummyBus()
    ch = IMessageChannel(
        {
            "enabled": True,
            "serverUrl": "https://server.example",
            "apiKey": "secret",
            "allowFrom": ["*"],
        },
        bus,
    )
    fake_http = FakeHttpClient()
    ch._http = fake_http

    media_path = tmp_path / "photo.jpg"
    media_path.write_bytes(b"jpg")

    await ch.send(
        OutboundMessage(
            channel="imessage",
            chat_id="+15551234567",
            content="First paragraph\n\nSecond paragraph",
            media=[str(media_path)],
        )
    )

    post_urls = [call[1] for call in fake_http.calls if call[0] == "POST"]
    assert "/chats/+15551234567/typing" in post_urls
    assert "/send" in post_urls
    assert "/send/file" in post_urls
    assert ("DELETE", "/chats/+15551234567/typing", {}) in fake_http.calls


@pytest.mark.asyncio
async def test_handle_remote_message_publishes_and_downloads_attachment(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.imessage.get_media_dir", lambda _name: tmp_path)

    bus = DummyBus()
    ch = IMessageChannel(
        {
            "enabled": True,
            "serverUrl": "https://server.example",
            "apiKey": "secret",
            "allowFrom": ["*"],
        },
        bus,
    )
    fake_http = FakeHttpClient()
    fake_http.attachments["att-1"] = b"png-bytes"
    ch._http = fake_http

    data = {
        "id": "msg-1",
        "from": "+15551234567",
        "chat": "+15551234567",
        "text": "hello",
        "attachments": [
            {
                "guid": "att-1",
                "transferName": "image.png",
            }
        ],
    }

    await ch._handle_remote_message(data)

    assert len(bus.inbound) == 1
    msg = bus.inbound[0]
    assert msg.channel == "imessage"
    assert msg.sender_id == "+15551234567"
    assert msg.chat_id == "+15551234567"
    assert "hello" in msg.content
    assert "[file:" in msg.content or "[image:" in msg.content
    assert Path(msg.media[0]).name == "image.png"
    assert ch._is_seen("msg-1") is True


@pytest.mark.asyncio
async def test_handle_remote_message_ignores_from_me_and_duplicates():
    bus = DummyBus()
    ch = IMessageChannel(
        {
            "enabled": True,
            "serverUrl": "https://server.example",
            "apiKey": "secret",
            "allowFrom": ["*"],
        },
        bus,
    )
    ch._http = FakeHttpClient()

    await ch._handle_remote_message({"id": "msg-me", "from": "me", "text": "ignore"})
    ch._mark_seen("msg-dup")
    await ch._handle_remote_message({"id": "msg-dup", "from": "+1555", "text": "ignore"})

    assert bus.inbound == []


def test_default_config_exposes_remote_only_shape():
    cfg = IMessageChannel.default_config()
    assert cfg["enabled"] is False
    assert cfg["serverUrl"] == ""
    assert cfg["apiKey"] == ""
    assert cfg["enableTypingIndicator"] is True
    assert cfg["seedHistoryOnStart"] is True
