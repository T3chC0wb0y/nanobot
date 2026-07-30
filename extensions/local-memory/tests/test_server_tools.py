from nanobot_local_memory.server import create_mcp_server


def _tool_fn(server, name: str):
    manager = getattr(server, "_tool_manager")
    return manager._tools[name].fn


def test_memory_build_context_returns_compact_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOBOT_LOCAL_MEMORY_DB", str(tmp_path / "memory.sqlite3"))
    server = create_mcp_server()

    capture = _tool_fn(server, "memory_capture_candidate")
    build_context = _tool_fn(server, "memory_build_context")

    capture(
        type="decision",
        domain="nanobot",
        title="Restart nanobot with agent helper",
        summary="Use the home-directory restart helper for nanobot restarts.",
        content="When nanobot needs a restart, use /home/bjohnson/.nanobot/bin/restart-by-agent.sh and verify the service after restart.",
        tags=["restart", "nanobot"],
    )

    result = build_context(query="how do we restart nanobot", include_candidates=True, limit=3, max_chars=400)

    assert result["ok"] is True
    assert result["count"] >= 1
    assert "Restart nanobot with agent helper" in result["context"]
    assert "home-directory restart helper" in result["context"]
    assert len(result["context"]) <= 400


def test_memory_search_and_build_context_support_multiple_domains_and_types(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOBOT_LOCAL_MEMORY_DB", str(tmp_path / "memory.sqlite3"))
    server = create_mcp_server()

    capture = _tool_fn(server, "memory_capture_candidate")
    promote = _tool_fn(server, "memory_promote")
    search = _tool_fn(server, "memory_search")
    build_context = _tool_fn(server, "memory_build_context")

    for record in (
        {
            "type": "preference",
            "domain": "engineering",
            "title": "Engineering preference",
            "summary": "Engineering preference summary.",
            "content": "Verify current local state before code changes.",
            "record_id": "engineering-preference",
        },
        {
            "type": "procedure",
            "domain": "operations",
            "title": "Operations procedure",
            "summary": "Operations procedure summary.",
            "content": "Verify current local state before service changes.",
            "record_id": "operations-procedure",
        },
        {
            "type": "policy",
            "domain": "personal",
            "title": "User policy",
            "summary": "User policy summary.",
            "content": "Avoid unverified workarounds.",
            "record_id": "user-policy",
        },
    ):
        capture(**record)
        promote(record["record_id"], promoted_by="reviewer")

    search_result = search(
        query="verify current local state",
        domains=["engineering", "operations"],
        types=["preference", "procedure"],
    )
    assert search_result["ok"] is True
    assert {record["id"] for record in search_result["results"]} == {
        "engineering-preference",
        "operations-procedure",
    }

    compatibility_result = search(
        query="avoid unverified",
        domain="personal",
        type="policy",
    )
    assert {record["id"] for record in compatibility_result["results"]} == {"user-policy"}

    context_result = build_context(
        query="verify current local state",
        domains=["engineering", "operations"],
        types=["preference", "procedure"],
        max_chars=500,
    )
    assert context_result["count"] == 2
    assert "Engineering preference" in context_result["context"]
    assert "Operations procedure" in context_result["context"]


def test_memory_search_and_build_context_reject_invalid_domains(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOBOT_LOCAL_MEMORY_DB", str(tmp_path / "memory.sqlite3"))
    server = create_mcp_server()

    search = _tool_fn(server, "memory_search")
    build_context = _tool_fn(server, "memory_build_context")

    search_result = search(query="anything", domain=".")
    assert search_result["ok"] is False
    assert search_result["message"].startswith("query failed, search with a valid domain or domains")
    assert search_result["count"] == 0
    assert search_result["results"] == []

    context_result = build_context(query="anything", domains=["operations", "bad-domain"])
    assert context_result["ok"] is False
    assert context_result["message"].startswith("query failed, search with a valid domain or domains")
    assert context_result["count"] == 0
    assert context_result["results"] == []
    assert context_result["context"] == ""


def test_memory_list_recent_rejects_invalid_domain(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOBOT_LOCAL_MEMORY_DB", str(tmp_path / "memory.sqlite3"))
    server = create_mcp_server()

    list_recent = _tool_fn(server, "memory_list_recent")

    result = list_recent(domain="bad-domain")

    assert result["ok"] is False
    assert result["message"].startswith("query failed, search with a valid domain or domains")
    assert result["count"] == 0
    assert result["records"] == []


def test_memory_list_recent_accepts_legacy_domain_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOBOT_LOCAL_MEMORY_DB", str(tmp_path / "memory.sqlite3"))
    server = create_mcp_server()

    capture = _tool_fn(server, "memory_capture_candidate")
    list_recent = _tool_fn(server, "memory_list_recent")

    capture(
        type="preference",
        domain="engineering",
        title="Engineering preference",
        summary="Engineering preference summary.",
        content="Verify branch state before changing code.",
        record_id="engineering-preference",
    )

    result = list_recent(domain="engineering")

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["records"][0]["id"] == "engineering-preference"
    assert result["records"][0]["domain"] == "project"
