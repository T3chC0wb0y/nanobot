from nanobot_local_memory.storage import SQLiteMemoryStore


def test_candidate_promote_search_and_deprecate(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")

    record = store.capture_candidate(
        record_type="resolution_pattern",
        domain="microsoft_365",
        title="Shared mailbox access request",
        summary="Reusable Exchange shared mailbox access workflow.",
        content="Read mailbox state, preview delegation, obtain approval, execute, and verify.",
        tags=["exchange", "shared-mailbox", "approval-required"],
        metadata={"source": "test"},
    )

    assert record.status == "candidate"
    assert store.search("shared mailbox") == []

    promoted = store.promote(record.id, promoted_by="Bob", note="validated")
    assert promoted.status == "promoted"
    assert promoted.metadata["promoted_by"] == "Bob"

    results = store.search("shared mailbox", domain="microsoft_365")
    assert len(results) == 1
    assert results[0]["id"] == record.id

    deprecated = store.deprecate(record.id, reason="superseded", deprecated_by="Bob")
    assert deprecated.status == "deprecated"
    assert deprecated.metadata["deprecation_reason"] == "superseded"
    assert store.search("shared mailbox") == []


def test_capture_with_same_id_updates_candidate(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")

    first = store.capture_candidate(
        record_id="lm_test",
        record_type="environment_fact",
        domain="nanobot",
        title="Initial title",
        summary="Initial summary",
        content="Initial content",
    )
    second = store.capture_candidate(
        record_id="lm_test",
        record_type="environment_fact",
        domain="nanobot",
        title="Updated title",
        summary="Updated summary",
        content="Updated content",
    )

    assert first.id == second.id == "lm_test"
    assert store.get("lm_test").title == "Updated title"
    assert len(store.list_recent()) == 1
