from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.bus.events import InboundMessage
from nanobot.config.schema import ChannelsConfig
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.session.manager import Session


def _mk_loop() -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    loop._TOOL_RESULT_MAX_CHARS = AgentLoop._TOOL_RESULT_MAX_CHARS
    return loop


def _make_agent_loop(tmp_path: Path, *, channels_config: ChannelsConfig | None = None) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        channels_config=channels_config,
    )


def test_save_turn_skips_multimodal_user_when_only_runtime_context() -> None:
    loop = _mk_loop()
    session = Session(key="test:runtime-only")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    loop._save_turn(
        session,
        [{"role": "user", "content": [{"type": "text", "text": runtime}]}],
        skip=0,
    )
    assert session.messages == []


def test_save_turn_keeps_image_placeholder_after_runtime_strip() -> None:
    loop = _mk_loop()
    session = Session(key="test:image")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    loop._save_turn(
        session,
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
        skip=0,
    )
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image]"}]


def test_save_turn_keeps_tool_results_under_16k() -> None:
    loop = _mk_loop()
    session = Session(key="test:tool-result")
    content = "x" * 12_000

    loop._save_turn(
        session,
        [{"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": content}],
        skip=0,
    )

    assert session.messages[0]["content"] == content


def test_save_turn_preserves_assistant_usage_metadata() -> None:
    loop = _mk_loop()
    session = Session(key="test:assistant-usage")

    loop._save_turn(
        session,
        [{
            "role": "assistant",
            "content": "hello",
            "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19, "cached_tokens": 4},
        }],
        skip=0,
    )

    assert session.messages[0]["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "total_tokens": 19,
        "cached_tokens": 4,
    }


@pytest.mark.asyncio
async def test_process_message_persists_provider_usage_in_session(tmp_path: Path) -> None:
    loop = _make_agent_loop(tmp_path)
    loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Hello!",
        tool_calls=[],
        usage={"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30, "cached_tokens": 6},
    ))
    loop.tools.get_definitions = MagicMock(return_value=[])

    msg = InboundMessage(channel="cli", sender_id="user1", chat_id="direct", content="Hi")
    result = await loop._process_message(msg)

    assert result is not None
    session = loop.sessions.get_or_create("cli:direct")
    assistant_messages = [m for m in session.messages if m.get("role") == "assistant"]
    assert assistant_messages
    assert assistant_messages[-1]["usage"] == {
        "prompt_tokens": 21,
        "completion_tokens": 9,
        "total_tokens": 30,
        "cached_tokens": 6,
    }


@pytest.mark.asyncio
async def test_process_message_sends_token_threshold_notification(tmp_path: Path) -> None:
    loop = _make_agent_loop(
        tmp_path,
        channels_config=ChannelsConfig(token_notify_threshold=25),
    )
    loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Hello!",
        tool_calls=[],
        usage={"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30, "cached_tokens": 6},
    ))
    loop.tools.get_definitions = MagicMock(return_value=[])

    sent = []
    original_publish = loop.bus.publish_outbound

    async def capture(msg):
        sent.append(msg)
        await original_publish(msg)

    loop.bus.publish_outbound = capture

    msg = InboundMessage(channel="telegram", sender_id="user1", chat_id="123", content="Hi")
    result = await loop._process_message(msg)

    assert result is not None
    assert len(sent) == 1
    assert sent[0].channel == "telegram"
    assert sent[0].chat_id == "123"
    assert sent[0].content == "This turn used 30 tokens (6 cached). It may be time to start a new session with /new."


@pytest.mark.asyncio
async def test_process_message_sends_token_threshold_notification_for_aggregated_turn_usage(tmp_path: Path) -> None:
    loop = _make_agent_loop(
        tmp_path,
        channels_config=ChannelsConfig(token_notify_threshold=50),
    )
    tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
    calls = iter([
        LLMResponse(
            content="Working",
            tool_calls=[tool_call],
            usage={"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30, "cached_tokens": 6},
        ),
        LLMResponse(
            content="Done",
            tool_calls=[],
            usage={"prompt_tokens": 15, "completion_tokens": 10, "total_tokens": 25, "cached_tokens": 4},
        ),
    ])
    loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
    loop.tools.get_definitions = MagicMock(return_value=[])

    sent = []
    original_publish = loop.bus.publish_outbound

    async def capture(msg):
        sent.append(msg)
        await original_publish(msg)

    loop.bus.publish_outbound = capture

    msg = InboundMessage(channel="telegram", sender_id="user1", chat_id="123", content="Hi")
    result = await loop._process_message(msg)

    assert result is not None
    notifications = [m for m in sent if m.content.startswith("This turn used ")]
    assert len(notifications) == 1
    assert notifications[0].content == "This turn used 55 tokens (10 cached). It may be time to start a new session with /new."


@pytest.mark.asyncio
async def test_process_message_skips_token_threshold_notification_below_threshold(tmp_path: Path) -> None:
    loop = _make_agent_loop(
        tmp_path,
        channels_config=ChannelsConfig(token_notify_threshold=50),
    )
    loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Hello!",
        tool_calls=[],
        usage={"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30, "cached_tokens": 6},
    ))
    loop.tools.get_definitions = MagicMock(return_value=[])

    sent = []
    original_publish = loop.bus.publish_outbound

    async def capture(msg):
        sent.append(msg)
        await original_publish(msg)

    loop.bus.publish_outbound = capture

    msg = InboundMessage(channel="telegram", sender_id="user1", chat_id="123", content="Hi")
    result = await loop._process_message(msg)

    assert result is not None
    assert sent == []


@pytest.mark.asyncio
async def test_process_message_appends_token_usage_to_final_response_when_enabled(tmp_path: Path) -> None:
    loop = _make_agent_loop(
        tmp_path,
        channels_config=ChannelsConfig(append_token_usage_to_response=True),
    )
    loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Hello!",
        tool_calls=[],
        usage={"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30, "cached_tokens": 6},
    ))
    loop.tools.get_definitions = MagicMock(return_value=[])

    msg = InboundMessage(channel="telegram", sender_id="user1", chat_id="123", content="Hi")
    result = await loop._process_message(msg)

    assert result is not None
    assert result.content == "Hello!\n\nThis turn used 30 tokens (6 cached)."
    session = loop.sessions.get_or_create("telegram:123")
    assistant_messages = [m for m in session.messages if m.get("role") == "assistant"]
    assert assistant_messages[-1]["content"] == "Hello!\n\nThis turn used 30 tokens (6 cached)."


@pytest.mark.asyncio
async def test_process_message_appends_aggregated_token_usage_to_final_response_when_enabled(tmp_path: Path) -> None:
    loop = _make_agent_loop(
        tmp_path,
        channels_config=ChannelsConfig(append_token_usage_to_response=True),
    )
    tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
    calls = iter([
        LLMResponse(
            content="Working",
            tool_calls=[tool_call],
            usage={"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30, "cached_tokens": 6},
        ),
        LLMResponse(
            content="Done",
            tool_calls=[],
            usage={"prompt_tokens": 15, "completion_tokens": 10, "total_tokens": 25, "cached_tokens": 4},
        ),
    ])
    loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.tools.execute = AsyncMock(return_value="ok")

    msg = InboundMessage(channel="telegram", sender_id="user1", chat_id="123", content="Hi")
    result = await loop._process_message(msg)

    assert result is not None
    assert result.content == "Done\n\nThis turn used 55 tokens (10 cached)."
