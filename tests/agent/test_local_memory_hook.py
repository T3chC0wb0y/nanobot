from nanobot.agent.local_memory_hook import LocalMemoryHook
from nanobot.agent.local_memory_runtime import build_local_memory_hooks
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config


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
