from __future__ import annotations

import json

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.local_memory import LocalMemoryConfig, RiskyActionBlockedError
from nanobot.agent.local_memory_hook import LocalMemoryHook
from nanobot.providers.base import ToolCallRequest


class StubToolRegistry:
    def __init__(self, responses: dict[str, object] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def has(self, name: str) -> bool:
        return name in self.responses

    async def execute(self, name: str, params: dict[str, object]) -> object:
        self.calls.append((name, params))
        response = self.responses[name]
        if isinstance(response, Exception):
            raise response
        return response


def _config(tmp_path) -> LocalMemoryConfig:
    return LocalMemoryConfig(
        enabled=True,
        trace_path=tmp_path / "memory-recall-trace.jsonl",
        min_query_length=1,
    )


@pytest.mark.asyncio
async def test_before_iteration_skips_when_builder_already_included(tmp_path) -> None:
    tools = StubToolRegistry(
        {
            "mcp_local_memory_memory_build_context": {
                "context": "Use repo-safe workflow first.",
                "results": [
                    {
                        "record_id": "mem-skip",
                        "type": "procedure",
                        "status": "promoted",
                        "title": "Repo workflow",
                        "summary": "Recall before changes.",
                    }
                ],
            }
        }
    )
    hook = LocalMemoryHook(_config(tmp_path), tools)
    context = AgentHookContext(
        iteration=0,
        messages=[{"role": "user", "content": "remember my preference"}],
        metadata={"local_memory_builder_included": True},
    )

    await hook.before_iteration(context)

    assert tools.calls == []
    assert "local_memory_builder_attempted" not in context.metadata
    assert "local_memory_injection" not in context.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_request",
    [
        "Implement the local memory patch for Nanobot",
        "Debug the local memory hook behavior",
        "Analyze this repo flow and suggest next steps",
        "Run tests for the local memory hook",
        "Check git branch status before coding",
    ],
)
async def test_normal_work_recall_does_not_block(tmp_path, user_request: str) -> None:
    tools = StubToolRegistry(
        {
            "mcp_local_memory_memory_build_context": {
                "context": "Use repo-safe workflow first.",
                "results": [
                    {
                        "record_id": "mem-1",
                        "type": "procedure",
                        "status": "promoted",
                        "title": "Repo workflow",
                        "summary": "Recall before changes.",
                    }
                ],
            }
        }
    )
    hook = LocalMemoryHook(_config(tmp_path), tools)
    context = AgentHookContext(iteration=0, messages=[{"role": "user", "content": user_request}])

    await hook.before_iteration(context)

    assert tools.calls
    assert context.metadata["local_memory_builder_attempted"] is True
    assert context.metadata["local_memory_status"] == "included"
    assert context.metadata["local_memory_memory_ids"] == ["mem-1"]
    injection = context.metadata["local_memory_injection"]
    assert injection.heading == "Supplemental local-memory recall"
    assert injection.content == "Use repo-safe workflow first."
    assert context.metadata["supplemental_sections"] == [
        "# Supplemental Local Memory\n\nUse repo-safe workflow first."
    ]


@pytest.mark.asyncio
async def test_promoted_procedure_guides_autonomous_action(tmp_path) -> None:
    tools = StubToolRegistry(
        {
            "mcp_local_memory_memory_build_context": {
                "context": "Use /home/bjohnson/.nanobot/bin/restart-by-agent.sh with verification.",
                "results": [
                    {
                        "record_id": "mem-restart",
                        "type": "procedure",
                        "status": "promoted",
                        "title": "Nanobot restart",
                        "summary": "Use restart-by-agent.sh.",
                    }
                ],
            }
        }
    )
    hook = LocalMemoryHook(_config(tmp_path), tools)
    context = AgentHookContext(
        iteration=0,
        messages=[{"role": "user", "content": "Restart the Nanobot service safely"}],
    )

    await hook.before_iteration(context)

    assert context.metadata["local_memory_builder_attempted"] is True
    assert context.metadata["local_memory_status"] == "included"
    assert context.metadata["local_memory_memory_ids"] == ["mem-restart"]
    injection = context.metadata["local_memory_injection"]
    assert "restart-by-agent.sh" in injection.content


@pytest.mark.asyncio
async def test_candidate_memory_is_not_instruction_for_risky_action(tmp_path) -> None:
    tools = StubToolRegistry(
        {
            "mcp_local_memory_memory_build_context": {
                "context": "Candidate note: maybe restart directly if needed.",
                "results": [
                    {
                        "record_id": "cand-1",
                        "type": "procedure",
                        "status": "candidate",
                        "title": "Unreviewed restart note",
                        "summary": "Try raw systemctl restart.",
                    }
                ],
            }
        }
    )
    hook = LocalMemoryHook(_config(tmp_path), tools)
    context = AgentHookContext(
        iteration=0,
        messages=[{"role": "user", "content": "systemctl restart nanobot gateway"}],
    )

    with pytest.raises(RiskyActionBlockedError):
        await hook.before_iteration(context)

    assert context.metadata["local_memory_builder_attempted"] is True
    assert context.metadata["local_memory_status"] == "included"
    assert context.metadata["local_memory_memory_ids"] == ["cand-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_request",
    [
        "kill nanobot pid 123",
        "pkill gateway",
        "killall agent",
        "terminate process listener",
    ],
)
async def test_protected_stack_direct_termination_blocks(tmp_path, user_request: str) -> None:
    tools = StubToolRegistry(
        {
            "mcp_local_memory_memory_build_context": {
                "context": "Use /home/bjohnson/.nanobot/bin/restart-by-agent.sh with verification.",
                "results": [
                    {
                        "record_id": "mem-restart",
                        "type": "procedure",
                        "status": "promoted",
                        "title": "Nanobot restart",
                        "summary": "Avoid direct kills.",
                    }
                ],
            }
        }
    )
    hook = LocalMemoryHook(_config(tmp_path), tools)
    context = AgentHookContext(iteration=0, messages=[{"role": "user", "content": user_request}])

    with pytest.raises(RiskyActionBlockedError):
        await hook.before_iteration(context)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_request",
    [
        "systemctl restart local-memory",
        "systemctl stop mcp service",
    ],
)
async def test_protected_stack_raw_systemctl_blocks_without_approved_helper(tmp_path, user_request: str) -> None:
    tools = StubToolRegistry(
        {
            "mcp_local_memory_memory_build_context": {
                "context": "Use the documented restart workflow with verification.",
                "results": [
                    {
                        "record_id": "mem-restart",
                        "type": "procedure",
                        "status": "promoted",
                        "title": "Nanobot restart",
                        "summary": "Avoid raw systemctl commands.",
                    }
                ],
            }
        }
    )
    hook = LocalMemoryHook(_config(tmp_path), tools)
    context = AgentHookContext(iteration=0, messages=[{"role": "user", "content": user_request}])

    with pytest.raises(RiskyActionBlockedError):
        await hook.before_iteration(context)


@pytest.mark.asyncio
async def test_approved_helper_path_allowed(tmp_path) -> None:
    tools = StubToolRegistry(
        {
            "mcp_local_memory_memory_build_context": {
                "context": "Use /home/bjohnson/.nanobot/bin/restart-by-agent.sh with verification.",
                "results": [
                    {
                        "record_id": "mem-restart",
                        "type": "procedure",
                        "status": "promoted",
                        "title": "Nanobot restart",
                        "summary": "Use restart-by-agent.sh.",
                    }
                ],
            }
        }
    )
    hook = LocalMemoryHook(_config(tmp_path), tools)
    context = AgentHookContext(
        iteration=0,
        messages=[{"role": "user", "content": "Use restart-by-agent.sh to restart nanobot safely"}],
    )

    await hook.before_iteration(context)

    injection = context.metadata["local_memory_injection"]
    assert "restart-by-agent.sh" in injection.content


@pytest.mark.asyncio
async def test_trace_does_not_store_raw_prompt(tmp_path) -> None:
    cfg = _config(tmp_path)
    tools = StubToolRegistry(
        {
            "mcp_local_memory_memory_build_context": {
                "context": "Respect Bob's repo workflow preference.",
                "results": [
                    {
                        "record_id": "mem-trace",
                        "type": "preference",
                        "status": "promoted",
                        "title": "Repo preference",
                        "summary": "Check git state first.",
                    }
                ],
            }
        }
    )
    hook = LocalMemoryHook(cfg, tools)
    raw_prompt = "Modify the agent runtime logic and keep secret token ABC123 hidden"
    context = AgentHookContext(iteration=0, messages=[{"role": "user", "content": raw_prompt}])

    await hook.before_iteration(context)

    lines = cfg.trace_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    payload = json.loads(lines[-1])
    assert payload["task_label"] == "meaningful work recall"
    assert payload["returned_memory_ids"] == ["mem-trace"]
    assert payload["used_memory_ids"] == ["mem-trace"]
    assert payload["ignored_memory_ids"] == []
    encoded = json.dumps(payload)
    assert raw_prompt not in encoded
    assert "ABC123" not in encoded
    assert "recall_query" not in payload
    assert "task_summary" not in payload


@pytest.mark.asyncio
async def test_capture_candidate_on_explicit_request(tmp_path) -> None:
    tools = StubToolRegistry(
        {
            "mcp_local_memory_memory_build_context": {
                "context": "",
                "results": [],
            },
            "mcp_local_memory_memory_capture_candidate": {"status": "ok", "record_id": "cand-1"},
        }
    )
    cfg = _config(tmp_path)
    cfg.capture_mode = "explicit"
    hook = LocalMemoryHook(cfg, tools)
    context = AgentHookContext(
        iteration=0,
        messages=[{"role": "user", "content": "Remember this: use focused tests only"}],
        final_content="Use focused tests only and avoid broad reruns unless required. This is stable enough to capture.",
    )
    context.stop_reason = "completed"

    await hook.after_iteration(context)

    assert any(name == "mcp_local_memory_memory_capture_candidate" for name, _ in tools.calls)


def test_tool_call_request_import_smoke() -> None:
    req = ToolCallRequest(id="1", name="exec", arguments="{}")
    assert req.name == "exec"
