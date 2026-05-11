import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.local_memory_hook import LocalMemoryHook
from nanobot.agent.local_memory_runtime import build_local_memory_hooks
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config


class FakeToolRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def has(self, name: str) -> bool:
        return name in {
            "mcp_local_memory_memory_build_context",
            "mcp_local_memory_memory_capture_candidate",
        }

    async def execute(self, name: str, params: dict) -> dict:
        self.calls.append((name, params))
        if name == "mcp_local_memory_memory_build_context":
            return {"context": "Stored runbook: use the restart script."}
        if name == "mcp_local_memory_memory_capture_candidate":
            return {"ok": True}
        raise AssertionError(f"Unexpected tool call: {name}")


def test_build_local_memory_hooks_enabled() -> None:
    cfg = Config.model_validate(
        {
            "tools": {
                "local_memory": {
                    "enabled": True,
                    "server_name": "local_memory",
                }
            }
        }
    )

    hooks = build_local_memory_hooks(cfg, ToolRegistry())

    assert len(hooks) == 1
    assert isinstance(hooks[0], LocalMemoryHook)


def test_build_local_memory_hooks_disabled() -> None:
    cfg = Config()

    assert build_local_memory_hooks(cfg, ToolRegistry()) == []


def test_build_local_memory_hooks_passes_capture_mode() -> None:
    cfg = Config.model_validate(
        {
            "tools": {
                "local_memory": {
                    "enabled": True,
                    "server_name": "local_memory",
                    "capture_mode": "explicit",
                }
            }
        }
    )

    hooks = build_local_memory_hooks(cfg, ToolRegistry())

    assert len(hooks) == 1
    assert hooks[0]._config.capture_mode == "explicit"


@pytest.mark.asyncio
async def test_after_iteration_normal_ops_prompt_does_not_capture() -> None:
    hook = LocalMemoryHook(
        build_local_memory_hooks(
            Config.model_validate(
                {
                    "tools": {
                        "local_memory": {
                            "enabled": True,
                            "capture_mode": "explicit",
                        }
                    }
                }
            ),
            ToolRegistry(),
        )[0]._config,
        FakeToolRegistry(),
    )
    context = AgentHookContext(
        iteration=0,
        messages=[{"role": "user", "content": "How do I restart the listener service on this box?"}],
        final_content=("Use /home/bjohnson/.nanobot/bin/restart-by-agent.sh and verify logs afterward. " * 2),
        stop_reason="completed",
    )

    await hook.after_iteration(context)

    assert [name for name, _ in hook._tools.calls] == []


@pytest.mark.asyncio
async def test_after_iteration_explicit_memory_cue_captures() -> None:
    tools = FakeToolRegistry()
    hook = LocalMemoryHook(
        build_local_memory_hooks(
            Config.model_validate(
                {
                    "tools": {
                        "local_memory": {
                            "enabled": True,
                            "capture_mode": "explicit",
                        }
                    }
                }
            ),
            ToolRegistry(),
        )[0]._config,
        tools,
    )
    context = AgentHookContext(
        iteration=0,
        messages=[{"role": "user", "content": "Remember this: restart the listener with the agent script and check health."}],
        final_content=("Restart with /home/bjohnson/.nanobot/bin/restart-by-agent.sh, then verify the listener health endpoint and recent logs. " * 2),
        stop_reason="completed",
    )

    await hook.after_iteration(context)

    assert any(name == "mcp_local_memory_memory_capture_candidate" for name, _ in tools.calls)


@pytest.mark.asyncio
async def test_before_iteration_recall_preserved() -> None:
    tools = FakeToolRegistry()
    hook = LocalMemoryHook(
        build_local_memory_hooks(
            Config.model_validate(
                {
                    "tools": {
                        "local_memory": {
                            "enabled": True,
                            "capture_mode": "off",
                        }
                    }
                }
            ),
            ToolRegistry(),
        )[0]._config,
        tools,
    )
    context = AgentHookContext(
        iteration=0,
        messages=[{"role": "user", "content": "What is the restart workflow for the listener service?"}],
        final_content=None,
        stop_reason=None,
    )

    await hook.before_iteration(context)

    assert any(name == "mcp_local_memory_memory_build_context" for name, _ in tools.calls)
    assert context.messages[0]["role"] == "system"
    assert "Supplemental local-memory recall" in context.messages[0]["content"]
