import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.local_memory import LocalMemoryConfig, should_search_local_memory
from nanobot.agent.local_memory_hook import LocalMemoryHook


class DummyTools:
    def __init__(self, available=None, execute_result=None):
        self.available = set(available or [])
        self.execute_result = execute_result or {}
        self.calls = []

    def has(self, name: str) -> bool:
        return name in self.available

    async def execute(self, name: str, params: dict):
        self.calls.append((name, params))
        return self.execute_result.get(name)


class DummyAgent:
    def __init__(self, tools):
        self.tools = tools


@pytest.mark.asyncio
async def test_local_memory_hook_prefers_build_context_on_first_iteration():
    tools = DummyTools(
        available={"mcp_local_memory_memory.build_context"},
        execute_result={
            "mcp_local_memory_memory.build_context": {"context": "Remembered project state"}
        },
    )
    hook = LocalMemoryHook(LocalMemoryConfig(enabled=True))
    ctx = AgentHookContext(
        iteration=1,
        messages=[
            {"role": "system", "content": "Primary nanobot system prompt"},
            {"role": "user", "content": "continue with the project"},
        ],
        agent=DummyAgent(tools),
    )

    await hook.before_iteration(ctx)

    assert tools.calls
    name, params = tools.calls[0]
    assert name == "mcp_local_memory_memory.build_context"
    assert "active project context" in params["query"].lower()
    assert ctx.messages[0]["role"] == "system"
    assert ctx.messages[0]["content"] == "Primary nanobot system prompt"
    assert ctx.messages[1]["role"] == "system"
    assert "Remembered project state" in ctx.messages[1]["content"]


@pytest.mark.asyncio
async def test_local_memory_hook_bootstrap_recall_without_user_text():
    tools = DummyTools(
        available={"mcp_local_memory_memory.build_context"},
        execute_result={
            "mcp_local_memory_memory.build_context": {"context": "Saved user preferences"}
        },
    )
    hook = LocalMemoryHook(LocalMemoryConfig(enabled=True, enable_bootstrap_recall=True))
    ctx = AgentHookContext(iteration=1, messages=[], agent=DummyAgent(tools))

    await hook.before_iteration(ctx)

    assert tools.calls
    _, params = tools.calls[0]
    assert "user preferences" in params["query"].lower()
    assert ctx.messages[0]["role"] == "system"
    assert "Saved user preferences" in ctx.messages[0]["content"]
    assert "Supplemental local-memory recall" in ctx.messages[0]["content"]


@pytest.mark.asyncio
async def test_local_memory_hook_falls_back_to_search_when_build_context_missing():
    tools = DummyTools(
        available={"mcp_local_memory_memory.search"},
        execute_result={
            "mcp_local_memory_memory.search": {
                "results": [
                    {
                        "title": "Preference",
                        "summary": "User likes concise replies",
                    }
                ]
            }
        },
    )
    hook = LocalMemoryHook(LocalMemoryConfig(enabled=True))
    ctx = AgentHookContext(
        iteration=1,
        messages=[{"role": "user", "content": "what do I prefer?"}],
        agent=DummyAgent(tools),
    )

    await hook.before_iteration(ctx)

    assert tools.calls
    assert tools.calls[0][0] == "mcp_local_memory_memory.search"
    assert ctx.messages[0]["role"] == "system"
    assert "Supplemental local-memory recall" in ctx.messages[0]["content"]
    assert "concise replies" in ctx.messages[0]["content"].lower()


@pytest.mark.asyncio
async def test_local_memory_hook_captures_candidate_on_completed_stop_reason():
    tools = DummyTools(
        available={
            "mcp_local_memory_memory.search",
            "mcp_local_memory_memory.capture_candidate",
        },
        execute_result={"mcp_local_memory_memory.capture_candidate": {"ok": True}},
    )
    hook = LocalMemoryHook(LocalMemoryConfig(enabled=True, auto_capture_candidates=True))
    ctx = AgentHookContext(
        iteration=1,
        messages=[{"role": "user", "content": "Please remember the runbook for status updates: use bullet points and include blockers first."}],
        agent=DummyAgent(tools),
        final_content="Understood — I'll use bullet points in future status updates, include blockers first, and preserve that runbook preference for future operational updates.",
        stop_reason="completed",
    )

    await hook.after_iteration(ctx)

    assert tools.calls
    assert tools.calls[0][0] == "mcp_local_memory_memory.capture_candidate"


def test_should_search_local_memory_routes_preferences_projects_and_operations():
    cfg = LocalMemoryConfig(enabled=True)

    assert should_search_local_memory("What do I prefer for response style?", cfg) is True
    assert should_search_local_memory("Continue the project and tell me the next step", cfg) is True
    assert should_search_local_memory("Show the runbook for restarting the gateway service", cfg) is True
    assert should_search_local_memory("hi", cfg) is False


@pytest.mark.asyncio
async def test_local_memory_hook_keeps_primary_system_prompt_first():
    tools = DummyTools(
        available={"mcp_local_memory_memory.build_context"},
        execute_result={
            "mcp_local_memory_memory.build_context": {"context": "Cross-session project notes"}
        },
    )
    hook = LocalMemoryHook(LocalMemoryConfig(enabled=True))
    ctx = AgentHookContext(
        iteration=1,
        messages=[
            {"role": "system", "content": "Primary nanobot instructions"},
            {"role": "user", "content": "continue the project"},
        ],
        agent=DummyAgent(tools),
    )

    await hook.before_iteration(ctx)

    assert [m["role"] for m in ctx.messages[:3]] == ["system", "system", "user"]
    assert ctx.messages[0]["content"] == "Primary nanobot instructions"
    assert "Supplemental local-memory recall" in ctx.messages[1]["content"]
    assert "Cross-session project notes" in ctx.messages[1]["content"]


@pytest.mark.asyncio
async def test_local_memory_hook_skips_bootstrap_when_disabled_and_no_user_text():
    tools = DummyTools(
        available={"mcp_local_memory_memory.build_context"},
        execute_result={
            "mcp_local_memory_memory.build_context": {"context": "Saved user preferences"}
        },
    )
    hook = LocalMemoryHook(LocalMemoryConfig(enabled=True, enable_bootstrap_recall=False))
    ctx = AgentHookContext(iteration=1, messages=[], agent=DummyAgent(tools))

    await hook.before_iteration(ctx)

    assert tools.calls == []
    assert ctx.messages == []


@pytest.mark.asyncio
async def test_local_memory_hook_ignores_non_first_iteration_bootstrap():
    tools = DummyTools(
        available={"mcp_local_memory_memory.build_context"},
        execute_result={
            "mcp_local_memory_memory.build_context": {"context": "Saved user preferences"}
        },
    )
    hook = LocalMemoryHook(LocalMemoryConfig(enabled=True, enable_bootstrap_recall=True))
    ctx = AgentHookContext(iteration=2, messages=[], agent=DummyAgent(tools))

    await hook.before_iteration(ctx)

    assert tools.calls == []
    assert ctx.messages == []
