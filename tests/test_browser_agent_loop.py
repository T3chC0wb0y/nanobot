from __future__ import annotations

from pathlib import Path

from nanobot.agent.loop import AgentLoop
from nanobot.config.schema import BrowserToolsConfig


class DummyProvider:
    generation = type("Generation", (), {"max_tokens": 1024})()

    def get_default_model(self) -> str:
        return "dummy-model"


class DummyBus:
    async def publish_outbound(self, *args, **kwargs):  # pragma: no cover - not used
        return None


def test_agent_loop_passes_browser_config_to_subagents(tmp_path: Path):
    browser_config = BrowserToolsConfig(enabled=True, headless=False, user_data_dir=str(tmp_path / "browser"))
    loop = AgentLoop(
        bus=DummyBus(),
        provider=DummyProvider(),
        workspace=tmp_path,
        browser_config=browser_config,
    )
    assert loop.browser_config is browser_config
    assert loop.subagents.browser_config is browser_config
    assert loop.tools.get("browser_open") is not None
    assert loop.tools.get("browser_text") is not None
    assert loop.tools.get("browser_screenshot") is not None
