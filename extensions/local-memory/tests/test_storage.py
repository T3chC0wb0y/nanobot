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
    assert record.type == "resolution_pattern"
    assert record.domain == "operations"
    assert record.metadata["capture_shaped_by"] == "local-memory-mcp"
    assert store.search("shared mailbox") == []

    promoted = store.promote(record.id, promoted_by="Bob", note="validated")
    assert promoted.status == "promoted"
    assert promoted.metadata["promoted_by"] == "Bob"

    results = store.search("shared mailbox", domain="operations")
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


def test_search_supports_multiple_domains_and_types(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")

    records = [
        store.capture_candidate(
            record_id="engineering-preference",
            record_type="preference",
            domain="engineering",
            title="Engineering technical preference",
            summary="Engineering preference summary.",
            content="Verify branch state before changing code.",
        ),
        store.capture_candidate(
            record_id="operations-procedure",
            record_type="procedure",
            domain="operations",
            title="Operations deployment procedure",
            summary="Operations procedure summary.",
            content="Verify service state before deploy.",
        ),
        store.capture_candidate(
            record_id="user-policy",
            record_type="policy",
            domain="personal",
            title="User technical policy",
            summary="User policy summary.",
            content="Avoid unverified workarounds in technical work.",
        ),
    ]
    for record in records:
        store.promote(record.id, promoted_by="reviewer")

    multi_domain_results = store.search(
        "verify",
        domains=["engineering", "operations"],
        record_types=["preference", "procedure"],
    )
    multi_domain_ids = {result["id"] for result in multi_domain_results}
    assert multi_domain_ids == {"engineering-preference", "operations-procedure"}
    assert {result["domain"] for result in multi_domain_results} == {"project", "operations"}

    compatibility_results = store.search(
        "verify branch",
        domain="engineering",
        record_type="preference",
    )
    assert {result["id"] for result in compatibility_results} == {"engineering-preference"}

    merged_filter_results = store.search(
        "technical",
        domain="engineering",
        domains=["personal"],
        record_type="preference",
        record_types=["policy"],
    )
    assert {result["id"] for result in merged_filter_results} == {
        "engineering-preference",
        "user-policy",
    }
