from __future__ import annotations

import json

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.local_memory import (
    DuplicateMemorySearchRequiredError,
    LocalMemoryConfig,
    MemoryCreationBlockedError,
    RiskyActionBlockedError,
    capture_candidate,
)
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
async def test_finalize_does_not_replace_code_answers_without_tool_use(tmp_path) -> None:
    tools = StubToolRegistry({})
    hook = LocalMemoryHook(_config(tmp_path), tools)
    context = AgentHookContext(
        iteration=0,
        messages=[{"role": "user", "content": "Read the code in nanobot/agent/local_memory_hook.py and explain the finalize_content path"}],
    )

    await hook.before_iteration(context)

    assert hook.finalize_content(context, "I can inspect that.") == "I can inspect that."
    assert context.metadata["adaptive_source_decision"]["source_type"] == "code"


@pytest.mark.asyncio
async def test_finalize_accepts_code_source_after_relevant_tool_call(tmp_path) -> None:
    tools = StubToolRegistry({})
    hook = LocalMemoryHook(_config(tmp_path), tools)
    context = AgentHookContext(
        iteration=0,
        messages=[{"role": "user", "content": "Read the code in nanobot/agent/local_memory_hook.py and explain the finalize_content path"}],
        tool_calls=[ToolCallRequest(id="call-1", name="read_file", arguments={"path": "nanobot/agent/local_memory_hook.py"})],
    )

    await hook.before_iteration(context)
    await hook.before_execute_tools(context)

    assert hook.finalize_content(context, "The code path is in local_memory_hook.py.") == "The code path is in local_memory_hook.py."


@pytest.mark.asyncio
async def test_finalize_keeps_answer_for_unrelated_tool_call(tmp_path) -> None:
    tools = StubToolRegistry({})
    hook = LocalMemoryHook(_config(tmp_path), tools)
    context = AgentHookContext(
        iteration=0,
        messages=[{"role": "user", "content": "Read the code in nanobot/agent/local_memory_hook.py and explain the finalize_content path"}],
        tool_calls=[ToolCallRequest(id="call-1", name="message", arguments={"content": "checking"})],
    )

    await hook.before_iteration(context)
    await hook.before_execute_tools(context)

    assert hook.finalize_content(context, "I sent a status message.") == "I sent a status message."
    assert context.metadata["adaptive_source_decision"]["source_type"] == "code"


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
    responses = {
        "mcp_local_memory_memory_build_context": {
            "context": "",
            "results": [],
        },
        "mcp_local_memory_memory_search": {"results": []},
        "mcp_local_memory_memory_capture_candidate": {"status": "ok", "record_id": "cand-1"},
    }

    class SearchAwareStubToolRegistry(StubToolRegistry):
        async def execute(self, name: str, params: dict[str, object]) -> object:
            self.calls.append((name, params))
            if name == "mcp_local_memory_memory_search":
                return {"results": []}
            response = self.responses[name]
            if isinstance(response, Exception):
                raise response
            return response

    tools = SearchAwareStubToolRegistry(responses)
    cfg = _config(tmp_path)
    cfg.capture_mode = "explicit"
    hook = LocalMemoryHook(cfg, tools)
    context = AgentHookContext(
        iteration=0,
        messages=[
            {
                "role": "user",
                "content": (
                    "Remember this procedure: use focused tests only for quick validation; "
                    "prefer targeted pytest paths; alias this as focused tests guidance; "
                    "store path /tmp/focused-tests.md"
                ),
            }
        ],
        final_content=(
            "Use focused tests only and avoid broad reruns unless required. "
            "Prefer targeted pytest paths for quick validation. "
            "This focused tests guidance is stable enough to capture."
        ),
    )
    context.stop_reason = "completed"

    await hook.before_iteration(context)

    duplicate = context.metadata.get("adaptive_source_duplicate_search")
    assert isinstance(duplicate, dict)
    queries = duplicate.get("queries")
    assert isinstance(queries, list)

    await hook.after_iteration(context)

    duplicate = context.metadata.get("adaptive_source_duplicate_search")
    assert isinstance(duplicate, dict)
    assert duplicate.get("completed") is True
    queries = duplicate.get("queries")
    assert isinstance(queries, list)
    steps = duplicate.get("steps")
    assert isinstance(steps, list)
    assert any(name == "mcp_local_memory_memory_capture_candidate" for name, _ in tools.calls)
    capture_calls = [params for name, params in tools.calls if name == "mcp_local_memory_memory_capture_candidate"]
    assert len(capture_calls) == 1
    assert capture_calls[0]["metadata"]["server_shapes_capture"] is True
    assert capture_calls[0]["metadata"]["adaptive_source_duplicate_search"]["completed"] is True
    assert context.metadata["local_memory_capture_result"]["record_id"] == "cand-1"
    assert context.final_content != "search incomplete"
    search_calls = [params for name, params in tools.calls if name == "mcp_local_memory_memory_search"]
    assert len(search_calls) >= 4


@pytest.mark.asyncio
async def test_capture_candidate_blocked_when_duplicate_search_finds_promoted_match(tmp_path) -> None:
    responses = {
        "mcp_local_memory_memory_build_context": {
            "context": "",
            "results": [],
        },
        "mcp_local_memory_memory_search": {"results": []},
        "mcp_local_memory_memory_capture_candidate": {"status": "ok", "record_id": "cand-1"},
    }

    class CanonicalMatchStubToolRegistry(StubToolRegistry):
        async def execute(self, name: str, params: dict[str, object]) -> object:
            self.calls.append((name, params))
            if name == "mcp_local_memory_memory_search":
                query = str(params.get("query") or "")
                if "focused tests" in query.lower():
                    return {
                        "results": [
                            {
                                "record_id": "mem-canonical-1",
                                "type": "procedure",
                                "domain": "operations",
                                "status": "promoted",
                                "title": "Use focused tests only",
                                "summary": "Canonical guidance for focused test reruns.",
                            }
                        ]
                    }
                return {"results": []}
            response = self.responses[name]
            if isinstance(response, Exception):
                raise response
            return response

    tools = CanonicalMatchStubToolRegistry(responses)
    cfg = _config(tmp_path)
    cfg.capture_mode = "explicit"
    hook = LocalMemoryHook(cfg, tools)
    context = AgentHookContext(
        iteration=0,
        messages=[
            {
                "role": "user",
                "content": (
                    "Remember this procedure: use focused tests only for quick validation; "
                    "prefer targeted pytest paths; alias this as focused tests guidance; "
                    "store path /tmp/focused-tests.md"
                ),
            }
        ],
        final_content=(
            "Use focused tests only and avoid broad reruns unless required. "
            "Prefer targeted pytest paths for quick validation. "
            "This focused tests guidance is stable enough to capture."
        ),
    )
    context.stop_reason = "completed"

    await hook.before_iteration(context)
    await hook.after_iteration(context)

    capture_call_count = sum(1 for name, _ in tools.calls if name == "mcp_local_memory_memory_capture_candidate")
    assert capture_call_count == 0

    duplicate = context.metadata.get("adaptive_source_duplicate_search")
    assert isinstance(duplicate, dict)
    assert duplicate.get("completed") is True
    steps = duplicate.get("steps")
    assert isinstance(steps, list)
    assert any(
        any(result.get("status") == "promoted" for result in step.get("result", {}).get("results", []))
        for step in steps
    )
    blocker = context.metadata.get("adaptive_source_duplicate_search_block")
    assert isinstance(blocker, dict)
    assert blocker.get("reason") == "duplicate existing canonical memory"
    assert context.final_content == (
        "Use focused tests only and avoid broad reruns unless required. "
        "Prefer targeted pytest paths for quick validation. "
        "This focused tests guidance is stable enough to capture."
    )

    with pytest.raises(MemoryCreationBlockedError) as excinfo:

        request = type("Req", (), {
            "type": "procedure",
            "domain": "operations",
            "title": "Use focused tests only",
            "summary": "Canonical guidance for focused test reruns.",
            "content": "Use focused tests only and avoid broad reruns unless required.",
            "tags": [],
            "metadata": {},
            "record_id": None,
        })()
        await capture_candidate(tools, request, cfg, metadata={})

    assert "search incomplete" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, DuplicateMemorySearchRequiredError)
    assert sum(1 for name, _ in tools.calls if name == "mcp_local_memory_memory_capture_candidate") == capture_call_count
    assert any(name == "mcp_local_memory_memory_search" for name, _ in tools.calls)


@pytest.mark.asyncio
async def test_adaptive_source_duplicate_search_runs_before_memory_capture(tmp_path) -> None:
    responses = {
        "mcp_local_memory_memory_build_context": {
            "context": "",
            "results": [],
        },
        "mcp_local_memory_memory_search": {"results": []},
        "mcp_local_memory_memory_capture_candidate": {"status": "ok", "record_id": "cand-1"},
    }

    class SearchAwareStubToolRegistry(StubToolRegistry):
        async def execute(self, name: str, params: dict[str, object]) -> object:
            self.calls.append((name, params))
            if name == "mcp_local_memory_memory_search":
                query = params.get("query")
                if query == "focused tests guidance":
                    return {"results": []}
                return {"results": [{"record_id": f"match-{len([c for c, _ in self.calls if c == name])}"}]}
            response = self.responses[name]
            if isinstance(response, Exception):
                raise response
            return response

    tools = SearchAwareStubToolRegistry(responses)
    cfg = _config(tmp_path)
    cfg.capture_mode = "explicit"
    hook = LocalMemoryHook(cfg, tools)
    context = AgentHookContext(
        iteration=0,
        messages=[
            {
                "role": "user",
                "content": (
                    "Remember this procedure: use focused tests only for quick validation; "
                    "prefer targeted pytest paths; alias this as focused tests guidance; "
                    "store path /tmp/focused-tests.md"
                ),
            }
        ],
        final_content=(
            "Use focused tests only and avoid broad reruns unless required. "
            "Prefer targeted pytest paths for quick validation. "
            "This focused tests guidance is stable enough to capture."
        ),
    )
    context.stop_reason = "completed"

    await hook.before_iteration(context)
    await hook.after_iteration(context)

    duplicate = context.metadata.get("adaptive_source_duplicate_search")
    assert isinstance(duplicate, dict)
    assert duplicate.get("completed") is True
    steps = duplicate.get("steps")
    assert isinstance(steps, list)
    assert all(not (step.get("type") == "unknown" and step.get("domain") == "unknown") for step in steps)
    plain_queries = {step.get("query") for step in steps if step.get("type") is None and step.get("domain") is None}
    assert any(query and query.startswith("Remember this procedure: use focused tests only") for query in plain_queries)
    assert any(query and query.startswith("Use focused tests only and avoid broad reruns unless required.") for query in plain_queries)
    assert any(name == "mcp_local_memory_memory_capture_candidate" for name, _ in tools.calls)


@pytest.mark.asyncio
async def test_capture_candidate_requires_duplicate_search_metadata(tmp_path) -> None:
    tools = StubToolRegistry(
        {
            "mcp_local_memory_memory_capture_candidate": {"status": "ok", "record_id": "cand-1"},
        }
    )
    cfg = _config(tmp_path)
    request = type("Req", (), {
        "type": "procedure",
        "domain": "operations",
        "title": "Title",
        "summary": "Summary",
        "content": "Content",
        "tags": [],
        "metadata": {},
        "record_id": None,
    })()

    with pytest.raises(MemoryCreationBlockedError) as excinfo:
        await capture_candidate(tools, request, cfg, metadata={})

    assert "search incomplete" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, DuplicateMemorySearchRequiredError)
    assert "search incomplete" in str(excinfo.value.__cause__)


def test_tool_call_request_import_smoke() -> None:
    req = ToolCallRequest(id="1", name="exec", arguments="{}")
    assert req.name == "exec"
