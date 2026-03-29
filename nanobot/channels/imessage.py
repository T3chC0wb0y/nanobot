"""Remote-only iMessage channel using Photon HTTP transport.

This channel intentionally omits local macOS database polling and AppleScript send
logic. It is designed for clean, reviewable remote agent deployments.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.utils.helpers import split_message

_PHOTON_PROXY_URL = "https://imessage-swagger.photon.codes"
_PHOTON_KIT_PATTERN = ".imsgd.photon.codes"
_DEFAULT_POLL_INTERVAL = 2.0
_MAX_MESSAGE_LEN = 6000
_AUDIO_EXTENSIONS = frozenset({".m4a", ".mp3", ".wav", ".aac", ".ogg", ".caf", ".opus"})


class IMessageConfig(Base):
    """Remote iMessage channel configuration."""

    enabled: bool = False
    server_url: str = ""
    api_key: str = ""
    proxy: str | None = None
    poll_interval: float = _DEFAULT_POLL_INTERVAL
    allow_from: list[str] = Field(default_factory=list)
    group_policy: str = "open"
    reply_to_message: bool = False
    enable_typing_indicator: bool = True
    seed_history_on_start: bool = True


def _split_paragraphs(text: str) -> list[str]:
    """Split text into iMessage-sized paragraph chunks."""
    parts: list[str] = []
    for para in text.split("\n\n"):
        stripped = para.strip()
        if stripped:
            parts.extend(split_message(stripped, _MAX_MESSAGE_LEN))
    return parts or [text]


def _is_photon_kit_url(url: str) -> bool:
    return _PHOTON_KIT_PATTERN in (urlparse(url).hostname or "")


def _resolve_proxy_url(server_url: str) -> str:
    if _is_photon_kit_url(server_url):
        logger.info("Photon Kit URL detected; routing through {}", _PHOTON_PROXY_URL)
        return _PHOTON_PROXY_URL
    return server_url


def _make_bearer_token(server_url: str, api_key: str) -> str:
    try:
        decoded = base64.b64decode(api_key, validate=True).decode()
        if "|" in decoded:
            return api_key
    except Exception:
        pass
    return base64.b64encode(f"{server_url}|{api_key}".encode()).decode()


def _extract_address(chat_id: str) -> str:
    if ";-;" in chat_id:
        return chat_id.split(";-;", 1)[1]
    if ";+;" in chat_id:
        return "group:" + chat_id.split(";+;", 1)[1]
    return chat_id


class IMessageChannel(BaseChannel):
    """Photon-backed iMessage channel for remote deployments."""

    name = "imessage"
    display_name = "iMessage"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return IMessageConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = IMessageConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: IMessageConfig = config
        self._http: httpx.AsyncClient | None = None
        self._processed_ids: OrderedDict[str, None] = OrderedDict()

    async def start(self) -> None:
        if not self.config.server_url:
            logger.error("iMessage server_url not configured")
            return
        if not self.config.api_key:
            logger.error("iMessage api_key not configured")
            return

        self._http = self._build_http_client()
        self._running = True

        if not await self._api_health():
            logger.warning("iMessage health check failed on startup; continuing")

        if self.config.seed_history_on_start:
            await self._seed_existing_message_ids()

        poll_interval = max(0.5, self.config.poll_interval)
        logger.info("iMessage remote polling started ({}s interval)", poll_interval)

        while self._running:
            try:
                await self._poll_remote()
            except Exception as e:
                logger.warning("iMessage poll error: {}", e)
            await asyncio.sleep(poll_interval)

    async def stop(self) -> None:
        self._running = False
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        if not self._http:
            logger.warning("iMessage HTTP client not initialized")
            return
        if (msg.metadata or {}).get("_progress"):
            return

        chat_id = str(msg.chat_id)
        if self.config.enable_typing_indicator:
            await self._api_start_typing(chat_id)

        try:
            if msg.content:
                for i, chunk in enumerate(_split_paragraphs(msg.content)):
                    body: dict[str, Any] = {"to": chat_id, "text": chunk, "service": "iMessage"}
                    if i == 0 and self.config.reply_to_message and msg.reply_to:
                        body["replyTo"] = msg.reply_to
                    result = await self._api_send(body)
                    if result is None:
                        raise RuntimeError(f"iMessage text delivery failed for {chat_id}")

            for media_path in msg.media or []:
                result = await self._api_send_file(chat_id, media_path)
                if result is None:
                    raise RuntimeError(f"iMessage media delivery failed: {media_path}")
        finally:
            if self.config.enable_typing_indicator:
                await self._api_stop_typing(chat_id)

    def _build_http_client(self) -> httpx.AsyncClient:
        token = _make_bearer_token(self.config.server_url, self.config.api_key)
        base_url = _resolve_proxy_url(self.config.server_url)
        return httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            proxy=self.config.proxy or None,
            timeout=30.0,
        )

    async def _poll_remote(self) -> None:
        messages = await self._api_get_messages(limit=50)
        if not messages:
            return
        for msg in reversed(messages):
            await self._handle_remote_message(msg)

    async def _seed_existing_message_ids(self) -> None:
        try:
            messages = await self._api_get_messages(limit=100)
            for msg in messages:
                message_id = msg.get("id") or msg.get("guid") or ""
                if message_id:
                    self._mark_seen(str(message_id))
            logger.info("Seeded {} existing iMessage IDs", len(self._processed_ids))
        except Exception as e:
            logger.debug("Could not seed iMessage history: {}", e)

    async def _handle_remote_message(self, data: dict[str, Any]) -> None:
        sender_raw = str(data.get("from") or "")
        if sender_raw == "me" or data.get("isFromMe"):
            return

        message_id = str(data.get("id") or data.get("guid") or "")
        if self._is_seen(message_id):
            return
        self._mark_seen(message_id)

        sender = sender_raw
        if not sender:
            handle = data.get("handle")
            if isinstance(handle, dict):
                sender = str(handle.get("address") or "")

        address = str(data.get("chat") or sender or "")
        if not address:
            chats = data.get("chats") or []
            chat_guid = chats[0].get("guid", "") if chats else ""
            address = _extract_address(str(chat_guid)) if chat_guid else sender

        is_group = address.startswith("group:") or ";+;" in address
        if is_group and self.config.group_policy == "ignore":
            return

        content = str(data.get("text") or "")
        media_paths: list[str] = []
        for att in data.get("attachments") or []:
            att_guid = str(att.get("guid") or "")
            name = str(att.get("transferName") or att.get("filename") or "")
            if not att_guid:
                continue
            local_path = await self._api_download_attachment(att_guid, name)
            if not local_path:
                continue
            mime, _ = mimetypes.guess_type(local_path)
            ext = Path(local_path).suffix.lower()
            if ext in _AUDIO_EXTENSIONS or (mime and mime.startswith("audio/")):
                transcription = await self.transcribe_audio(local_path)
                if transcription:
                    tag = f"[Voice Message: {transcription}]"
                    content = f"{content}\n{tag}" if content else tag
                    continue
            media_paths.append(local_path)
            tag = "image" if mime and mime.startswith("image/") else "file"
            marker = f"[{tag}: {local_path}]"
            content = f"{content}\n{marker}" if content else marker

        await self._api_mark_read(address)
        await self._handle_message(
            sender_id=sender,
            chat_id=address,
            content=content,
            media=media_paths,
            metadata={
                "imessage": {
                    "is_group": is_group,
                    "message_id": message_id,
                    "source": "remote",
                    "timestamp": data.get("sentAt") or data.get("dateCreated"),
                }
            },
        )

    async def _api_health(self) -> bool:
        if not self._http:
            return False
        try:
            resp = await self._http.get("/health")
            return resp.is_success
        except Exception as e:
            logger.debug("iMessage health check failed: {}", e)
            return False

    async def _api_get_messages(self, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._get("/messages", params={"limit": limit})
        return data if isinstance(data, list) else []

    async def _api_send(self, body: dict[str, Any]) -> dict[str, Any] | None:
        return await self._post_json("/send", body)

    async def _api_send_file(self, to: str, file_path: str) -> dict[str, Any] | None:
        if not self._http:
            return None
        path = Path(file_path)
        if not path.exists():
            logger.warning("iMessage attachment not found: {}", file_path)
            return None
        mime, _ = mimetypes.guess_type(str(path))
        ext = path.suffix.lower()
        data: dict[str, str] = {"to": to}
        if ext in _AUDIO_EXTENSIONS or (mime or "").startswith("audio/"):
            data["audio"] = "true"
        with path.open("rb") as f:
            resp = await self._http.post(
                "/send/file",
                data=data,
                files={"file": (path.name, f, mime or "application/octet-stream")},
            )
        return self._unwrap(resp)

    async def _api_download_attachment(self, att_guid: str, filename: str) -> str | None:
        if not self._http:
            return None
        try:
            resp = await self._http.get(f"/attachments/{att_guid}")
            if not resp.is_success:
                return None
            media_dir = get_media_dir("imessage")
            safe_name = Path(filename).name if filename else f"{att_guid.replace('/', '_')}.bin"
            dest = (media_dir / safe_name).resolve()
            if not dest.is_relative_to(media_dir.resolve()):
                dest = (media_dir / f"{att_guid.replace('/', '_')}.bin").resolve()
            dest.write_bytes(resp.content)
            return str(dest)
        except Exception as e:
            logger.warning("Failed to download iMessage attachment {}: {}", att_guid, e)
            return None

    async def _api_mark_read(self, address: str) -> None:
        if not self._http:
            return
        try:
            await self._http.post(f"/chats/{address}/read")
        except Exception as e:
            logger.debug("iMessage mark-read failed: {}", e)

    async def _api_start_typing(self, address: str) -> None:
        if not self._http:
            return
        try:
            await self._http.post(f"/chats/{address}/typing")
        except Exception as e:
            logger.debug("iMessage typing start failed: {}", e)

    async def _api_stop_typing(self, address: str) -> None:
        if not self._http:
            return
        try:
            await self._http.request("DELETE", f"/chats/{address}/typing")
        except Exception as e:
            logger.debug("iMessage typing stop failed: {}", e)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self._http:
            return None
        try:
            resp = await self._http.get(path, params=params)
            return self._unwrap(resp)
        except Exception as e:
            logger.warning("iMessage GET {} failed: {}", path, e)
            return None

    async def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any] | None:
        if not self._http:
            return None
        try:
            resp = await self._http.post(path, json=body)
            if not resp.is_success:
                logger.warning("iMessage POST {} HTTP {}", path, resp.status_code)
            return self._unwrap(resp)
        except Exception as e:
            logger.warning("iMessage POST {} failed: {}", path, e)
            raise

    @staticmethod
    def _unwrap(resp: httpx.Response) -> Any:
        if not resp.is_success:
            return None
        try:
            body = resp.json()
        except Exception:
            return None
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    def _is_seen(self, message_id: str) -> bool:
        return bool(message_id) and message_id in self._processed_ids

    def _mark_seen(self, message_id: str) -> None:
        if not message_id:
            return
        self._processed_ids[message_id] = None
        while len(self._processed_ids) > 1000:
            self._processed_ids.popitem(last=False)
