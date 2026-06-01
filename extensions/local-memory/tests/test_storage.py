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


def test_missing_record_operations_raise_key_error(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")

    for operation in (
        lambda: store.promote("missing-record", promoted_by="reviewer"),
        lambda: store.deprecate("missing-record", reason="not found", deprecated_by="reviewer"),
    ):
        try:
            operation()
        except KeyError as exc:
            assert "missing-record" in str(exc)
        else:
            raise AssertionError("Expected KeyError for missing memory record")

    assert store.get("missing-record") is None


def test_search_inclusion_flags_for_candidates_and_deprecated(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")

    candidate = store.capture_candidate(
        record_id="candidate-record",
        record_type="procedure",
        domain="nanobot",
        title="Candidate restart procedure",
        summary="Candidate procedure for restart notifications.",
        content="Candidate restart notification flow.",
        tags=["restart", "candidate"],
    )
    promoted = store.capture_candidate(
        record_id="promoted-record",
        record_type="procedure",
        domain="nanobot",
        title="Promoted restart procedure",
        summary="Promoted procedure for restart notifications.",
        content="Promoted restart notification flow.",
        tags=["restart", "promoted"],
    )
    deprecated = store.capture_candidate(
        record_id="deprecated-record",
        record_type="procedure",
        domain="nanobot",
        title="Deprecated restart procedure",
        summary="Deprecated procedure for restart notifications.",
        content="Deprecated restart notification flow.",
        tags=["restart", "deprecated"],
    )

    store.promote(promoted.id, promoted_by="reviewer")
    store.promote(deprecated.id, promoted_by="reviewer")
    store.deprecate(deprecated.id, reason="superseded", deprecated_by="reviewer")

    default_ids = {result["id"] for result in store.search("restart procedure")}
    candidate_ids = {
        result["id"]
        for result in store.search("restart procedure", include_candidates=True)
    }
    all_ids = {
        result["id"]
        for result in store.search(
            "restart procedure",
            include_candidates=True,
            include_deprecated=True,
        )
    }

    assert default_ids == {promoted.id}
    assert candidate_ids == {candidate.id, promoted.id}
    assert all_ids == {candidate.id, promoted.id, deprecated.id}


def test_fixed_domain_taxonomy_normalizes_aliases(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")

    record = store.capture_candidate(
        record_id="alias-record",
        record_type="procedure",
        domain="nanobot",
        title="Nanobot workflow",
        summary="Workflow for Nanobot maintenance.",
        content="Use the repository workflow for Nanobot maintenance.",
    )
    store.promote(record.id, promoted_by="reviewer")

    assert record.domain == "project"
    assert store.get("alias-record").domain == "project"
    assert [result["id"] for result in store.search("workflow", domain="nanobot")] == ["alias-record"]
    assert [result["id"] for result in store.search("workflow", domains=["engineering"])] == ["alias-record"]


def test_fixed_domain_taxonomy_rejects_unknown_domains(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")

    try:
        store.capture_candidate(
            record_type="procedure",
            domain="unknown-domain",
            title="Unknown",
            summary="Unknown domain should fail.",
            content="Unknown domain should fail.",
        )
    except ValueError as exc:
        assert "Invalid memory domain" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown memory domain")
