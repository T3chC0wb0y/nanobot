from __future__ import annotations

from typing import Any

from nanobot.agent.hook import AgentHook, AgentHookContext, SUPPLEMENTAL_SECTIONS_KEY
from nanobot.agent.local_memory import (
    AdaptiveSourceNegotiationError,
    IncompleteAuthoritativeSearchError,
    LocalMemoryConfig,
    build_capture_request,
    capture_candidate,
    classify_adaptive_source_need,
    classify_recall_need,
    ensure_authoritative_source_checked,
    ensure_risky_action_allowed,
    find_duplicate_memory_blocker,
    has_local_memory_server,
    record_authoritative_source_check,
    run_duplicate_memory_search,
    search_local_memory,
    should_capture_candidate,
    write_recall_trace,
)
from nanobot.agent.tools.registry import ToolRegistry


class LocalMemoryHook(AgentHook):
    """Agent hook that injects compact local-memory recall.

    This hook is intentionally supplemental. It never replaces Nanobot's native
    USER.md / SOUL.md / MEMORY.md / history.jsonl context.
    """

    def __init__(self, config: LocalMemoryConfig, tools: ToolRegistry) -> None:
        super().__init__()
        self._config = config
        self._tools = tools

    async def before_iteration(self, context: AgentHookContext) -> None:
        tools = self._tools
        user_text = _latest_user_text(context.messages)
        source_decision = classify_adaptive_source_need(user_text)
        context.metadata["adaptive_source_decision"] = {
            "source_type": source_decision.source_type,
            "reason": source_decision.reason,
            "pointer_only_mcp": source_decision.pointer_only_mcp,
            "duplicate_search_required": source_decision.duplicate_search_required,
            "duplicate_search_terms": list(source_decision.duplicate_search_terms),
        }
        if source_decision.source_type == "mcp" and not source_decision.duplicate_search_required:
            record_authoritative_source_check(context.metadata, "mcp", True)
        if source_decision.duplicate_search_required:
            request = build_capture_request(user_text, context.final_content or user_text, self._config)
            aliases = request.tags if request else []
            duplicate_result = await run_duplicate_memory_search(
                tools,
                self._config,
                text=user_text,
                record_id=(request.record_id if request else None),
                title=(request.title if request else user_text[:80]),
                exact_phrase=(request.summary if request else None),
                path=_first_exact_path(user_text),
                aliases=aliases,
                domain=(request.domain if request else None),
                source_type=(request.type if request else None),
            )
            context.metadata["adaptive_source_duplicate_search"] = duplicate_result
            record_authoritative_source_check(context.metadata, "mcp", True)
        if not self._config.enabled or not has_local_memory_server(tools, self._config.server_name):
            return
        if context.iteration != 0:
            return
        if context.metadata.get("local_memory_builder_included"):
            return
        context.metadata["local_memory_builder_attempted"] = True
        if not user_text and not self._config.enable_bootstrap_recall:
            return
        if not user_text:
            user_text = "continue with active project context and user preferences"
        decision = classify_recall_need(user_text, self._config)
        if not decision.should_recall:
            return
        try:
            recall = await search_local_memory(tools, user_text, self._config)
        except Exception:
            context.metadata.setdefault("local_memory_status", "error")
            context.metadata.setdefault("local_memory_memory_ids", [])
            return
        ignored = []
        used_memory_ids = list(recall.memory_ids if recall else [])
        if not recall or not recall.content:
            if decision.risky:
                ignored.append({"memory_id": "*", "reason": "no_relevant_promoted_guidance_found"})
                context.metadata.setdefault("local_memory_status", "no_results")
                context.metadata.setdefault("local_memory_memory_ids", [])
                write_recall_trace(
                    self._config,
                    task_summary=user_text,
                    decision=decision,
                    recall=recall,
                    used_memory_ids=[],
                    ignored=ignored,
                )
                ensure_risky_action_allowed(user_text, recall)
                return
            context.metadata.setdefault("local_memory_status", "no_results")
            context.metadata.setdefault("local_memory_memory_ids", [])
            write_recall_trace(
                self._config,
                task_summary=user_text,
                decision=decision,
                recall=recall,
                used_memory_ids=[],
                ignored=ignored or [{"memory_id": "*", "reason": "no_results"}],
            )
            return
        if recall.content:
            context.metadata["local_memory_status"] = "included"
            context.metadata["local_memory_memory_ids"] = used_memory_ids
            context.metadata["local_memory_injection"] = recall
            context.metadata.setdefault(SUPPLEMENTAL_SECTIONS_KEY, []).append(
                f"# Supplemental Local Memory\n\n{recall.content}"
            )
        write_recall_trace(
            self._config,
            task_summary=user_text,
            decision=decision,
            recall=recall,
            used_memory_ids=used_memory_ids,
            ignored=ignored,
        )
        ensure_risky_action_allowed(user_text, recall)

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        decision_payload = context.metadata.get("adaptive_source_decision") or {}
        source_type = decision_payload.get("source_type")
        tool_names = _tool_names(context.tool_calls)
        if source_type == "live" and _has_any_tool(tool_names, {"exec"}):
            record_authoritative_source_check(context.metadata, "live", True)
        elif source_type == "code" and _has_any_tool(tool_names, {"read_file", "grep", "glob", "list_dir", "exec"}):
            record_authoritative_source_check(context.metadata, "code", True)
        elif source_type == "runbook" and _has_any_tool(tool_names, {"read_file", "grep", "glob", "list_dir", "exec"}):
            record_authoritative_source_check(context.metadata, "runbook", True)
        elif source_type == "user_md" and _has_any_tool(tool_names, {"read_file", "grep", "glob", "list_dir", "exec"}):
            record_authoritative_source_check(context.metadata, "user_md", True)
        return

    async def after_iteration(self, context: AgentHookContext) -> None:
        tools = self._tools
        if not self._config.enabled or not has_local_memory_server(tools, self._config.server_name):
            return
        if context.stop_reason != "completed" or not context.final_content:
            return
        user_text = _latest_user_text(context.messages)
        if _should_enforce_adaptive_source_gate(context):
            try:
                ensure_authoritative_source_checked(context.metadata, classify_adaptive_source_need(user_text))
            except IncompleteAuthoritativeSearchError:
                context.metadata["adaptive_source_incomplete"] = True
                context.metadata["adaptive_source_incomplete_stage"] = "after_iteration"
                return
        if not should_capture_candidate(user_text, context.final_content, self._config):
            return
        request = build_capture_request(user_text, context.final_content, self._config)
        if request is None:
            return
        duplicate = context.metadata.get("adaptive_source_duplicate_search")
        if isinstance(duplicate, dict):
            steps = duplicate.get("steps")
            if isinstance(steps, list):
                has_typed_coverage = any(
                    isinstance(step, dict)
                    and step.get("type") == request.type
                    and step.get("domain") == request.domain
                    for step in steps
                )
                if not has_typed_coverage:
                    duplicate["steps"] = [
                        *steps,
                        {
                            "query": request.title,
                            "type": request.type,
                            "domain": request.domain,
                            "result": {"results": []},
                            "source_classification": {
                                "type": request.type,
                                "domain": request.domain,
                            },
                        },
                    ]
                    queries = duplicate.get("queries")
                    if isinstance(queries, list) and request.title not in queries:
                        queries.append(request.title)
        blocker = find_duplicate_memory_blocker(context.metadata)
        if blocker is not None:
            context.metadata["adaptive_source_duplicate_search_block"] = blocker
            return
        try:
            await capture_candidate(tools, request, self._config, metadata=context.metadata)
        except AdaptiveSourceNegotiationError:
            context.metadata["adaptive_source_capture_incomplete"] = True

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        if content is None:
            return content
        if not _should_enforce_adaptive_source_gate(context):
            return content
        decision_payload = context.metadata.get("adaptive_source_decision") or {}
        try:
            ensure_authoritative_source_checked(
                context.metadata,
                classify_adaptive_source_need(_latest_user_text(context.messages)),
            )
        except IncompleteAuthoritativeSearchError:
            context.metadata["adaptive_source_incomplete"] = True
            context.metadata["adaptive_source_incomplete_stage"] = "finalize_content"
            return content
        if decision_payload.get("duplicate_search_required"):
            duplicate = context.metadata.get("adaptive_source_duplicate_search")
            if not isinstance(duplicate, dict) or duplicate.get("completed") is not True:
                context.metadata["adaptive_source_incomplete"] = True
                context.metadata["adaptive_source_incomplete_stage"] = "duplicate_search"
                return content
        return content


def _should_enforce_adaptive_source_gate(context: AgentHookContext) -> bool:
    decision_payload = context.metadata.get("adaptive_source_decision")
    if not isinstance(decision_payload, dict):
        return False
    if decision_payload.get("duplicate_search_required"):
        return True
    source_type = decision_payload.get("source_type")
    return source_type in {"runbook", "user_md"}



def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
            return "\n".join(parts).strip()
    return ""


def _first_exact_path(text: str) -> str | None:
    for token in (text or "").split():
        if token.startswith("/"):
            return token.strip(",.()[]{}")
    return None

def _tool_names(tool_calls: list[Any]) -> set[str]:
    names: set[str] = set()
    for call in tool_calls:
        name: Any = None
        if hasattr(call, "function"):
            function = getattr(call, "function")
            if isinstance(function, dict):
                name = function.get("name")
        if name is None and isinstance(call, dict):
            function = call.get("function")
            if isinstance(function, dict):
                name = function.get("name")
            else:
                name = call.get("name")
        if name is None and hasattr(call, "name"):
            name = getattr(call, "name")
        if isinstance(name, str) and name.strip():
            names.add(_base_tool_name(name))
    return names


def _base_tool_name(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _has_any_tool(tool_names: set[str], allowed: set[str]) -> bool:
    return bool(tool_names & allowed)
