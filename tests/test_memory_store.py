from pathlib import Path

from alter.core.memory import MemoryStore


def test_memory_search_can_filter_by_kind(tmp_path: Path):
    db = tmp_path / "mem.sqlite3"
    store = MemoryStore(path=db)
    try:
        store.add_event(owner="o", session_id="s", kind="user", content="I like vim", meta={})
        store.add_event(owner="o", session_id="s", kind="assistant", content="You like emacs", meta={})
        store.add_event(owner="o", session_id="s", kind="tool", content="tool_id=system.info status=ok", meta={})

        hits = store.search(owner="o", query="like", limit=10, kinds=["user"])
        assert [h.kind for h in hits] == ["user"]
    finally:
        store.close()


def test_memory_store_redacts_common_secrets(tmp_path: Path):
    db = tmp_path / "mem.sqlite3"
    store = MemoryStore(path=db, redact_secrets=True)
    try:
        ev = store.add_event(owner="o", session_id="s", kind="note", content="api_key=sk-1234567890abcdef1234567890", meta={})
        assert "<redacted>" in ev.content
        assert ev.meta.get("_redacted") is True
    finally:
        store.close()
