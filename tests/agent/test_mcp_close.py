from __future__ import annotations

import asyncio

import pytest

from nanobot.agent.loop import AgentLoop


class _SlowStack:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        await asyncio.sleep(0.01)
        self.closed = True


@pytest.mark.asyncio
async def test_close_mcp_clears_stacks_after_deferred_close() -> None:
    loop = AgentLoop.__new__(AgentLoop)
    loop._background_tasks = []
    stack = _SlowStack()
    loop._mcp_stacks = {"local_memory": stack}

    await AgentLoop.close_mcp(loop)

    assert loop._mcp_stacks == {}
    assert stack.closed is True


@pytest.mark.asyncio
async def test_close_mcp_survives_cancellation_and_finishes_cleanup() -> None:
    loop = AgentLoop.__new__(AgentLoop)
    loop._background_tasks = []
    stack = _SlowStack()
    loop._mcp_stacks = {"local_memory": stack}

    task = asyncio.create_task(AgentLoop.close_mcp(loop))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert loop._mcp_stacks == {}
    assert stack.closed is True
