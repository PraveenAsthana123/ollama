import time

from scripts.collective_memory import MemoryStore


def test_scoped_search_deduplication_and_private_storage(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    first = store.put(scope="team", namespace="payments", owner="agent-a", provenance="test-run",
                      content="Invoice reconciliation requires account matching", tags=["invoice"],
                      trust="verified", ttl=3600, actor="supervisor")
    duplicate = store.put(scope="team", namespace="payments", owner="agent-a", provenance="test-run",
                          content="Invoice reconciliation requires account matching", tags=["invoice"],
                          trust="verified", ttl=3600, actor="supervisor")
    assert first["deduplicated"] is False
    assert duplicate["deduplicated"] is True
    assert (tmp_path / "memory.db").stat().st_mode & 0o777 == 0o600
    assert len(store.search("invoice matching", ["team"], 5, 100)) == 1
    assert store.search("invoice matching", ["agent"], 5, 100) == []


def test_retrieval_is_token_bounded_and_marks_untrusted_evidence(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    for index in range(3):
        store.put(scope="task", namespace="t1", owner="a", provenance="run",
                  content=f"database timeout finding {index} " + "detail " * 20, tags=["database"],
                  trust="observed", ttl=3600, actor="a")
    result = store.search("database timeout", ["task"], 10, 50)
    assert len(result) == 1
    assert "untrusted evidence" in result[0]["instruction"]


def test_expiry_forget_and_audit(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    expired = store.put(scope="task", namespace="t", owner="a", provenance="run",
                        content="temporary result", tags=[], trust="observed", ttl=-1, actor="a")
    assert store.search("temporary", ["task"], 5, 100) == []
    assert store.stats()["expired"] == 1
    active = store.put(scope="agent", namespace="a", owner="a", provenance="run",
                       content="durable preference", tags=[], trust="verified", ttl=3600, actor="a")
    assert store.forget(active["id"], "supervisor") is True
    assert store.connection.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 3
