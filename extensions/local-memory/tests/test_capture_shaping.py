from __future__ import annotations

import pytest

from nanobot_local_memory.capture_shaping import shape_capture_candidate


def test_shape_capture_candidate_normalizes_fields_and_infers_tags() -> None:
    shaped = shape_capture_candidate(
        record_type="runbook",
        domain="ops",
        title="  **Restart Workflow**  ",
        summary="",
        content="Use /home/bjohnson/.nanobot/bin/restart-by-agent.sh for the Nanobot listener workflow.",
        tags=[" Nanobot ", "nanobot", "Unsafe Tag!!"],
        metadata={"source": "test"},
    )

    assert shaped.record_type == "procedure"
    assert shaped.domain == "operations"
    assert shaped.title == "Restart Workflow"
    assert shaped.summary == "Use /home/bjohnson/.nanobot/bin/restart-by-agent.sh for the Nanobot listener workflow."
    assert shaped.tags[:3] == ["nanobot", "unsafe-tag", "procedure"]
    assert "path" in shaped.tags
    assert shaped.metadata["source"] == "test"
    assert shaped.metadata["capture_shaped_by"] == "local-memory-mcp"


def test_shape_capture_candidate_infers_type_and_domain_for_local_memory_overlay() -> None:
    shaped = shape_capture_candidate(
        record_type="unknown",
        domain="unknown",
        title="",
        summary="",
        content="The local-memory MCP repo owns memory_capture_candidate shaping; Nanobot should keep only thin hooks for overlay onto nightly.",
    )

    assert shaped.record_type == "project"
    assert shaped.domain == "memory"
    assert shaped.title.startswith("The local-memory MCP repo owns")
    assert {"project", "memory", "local-memory", "mcp", "nanobot", "overlay"}.issubset(set(shaped.tags))


def test_shape_capture_candidate_rejects_secrets() -> None:
    with pytest.raises(ValueError, match="secret"):
        shape_capture_candidate(
            record_type="fact",
            domain="operations",
            title="bad",
            summary="bad",
            content="The api key is abc123 and should not be stored.",
        )
