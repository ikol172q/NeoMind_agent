"""LocalVectorStore with RAG turned off — the path that actually runs.

faiss-cpu and sentence-transformers live in the optional ``rag`` extra
and are not installed by default, so ``available`` is False and every
call takes the degraded branch. tests/test_search_vector_store_full.py
skips its whole module on ``skipif(not HAS_FAISS)``, which means the
branch this machine really executes had no coverage at all — the
opposite of what the skip suggests.

The switches are forced off rather than read, so these assert the same
contract whether or not the extra is installed. test_crawl4ai_adapter_full
already does this for its own optional dependency.
"""
from __future__ import annotations

import pytest

from agent.search import vector_store as vs
from agent.search.vector_store import LocalVectorStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "HAS_FAISS", False)
    monkeypatch.setattr(vs, "HAS_SBERT", False)
    return LocalVectorStore(storage_dir=str(tmp_path))


def test_constructing_without_the_extra_does_not_raise(store):
    assert store.available is False


def test_add_results_reports_nothing_stored(store):
    added = store.add_results("query", [
        {"url": "http://example.com", "title": "t", "snippet": "body"},
    ])
    assert added == 0


def test_find_similar_returns_no_matches(store):
    assert store.find_similar("query", top_k=3) == []


def test_get_stats_says_why_it_is_unavailable(store):
    stats = store.get_stats()
    assert stats["available"] is False
    reason = stats.get("reason", "")
    assert "faiss" in reason and "sentence-transformers" in reason, (
        f"stats should name the missing packages, got {reason!r}"
    )


def test_clear_is_a_no_op_rather_than_an_error(store):
    assert store.clear() is None


def test_repeated_calls_stay_degraded(store):
    """No call may flip the switch on or start half-initialising."""
    store.add_results("q", [{"url": "http://a", "title": "a", "snippet": "a"}])
    store.find_similar("q")
    store.clear()
    assert store.available is False
    assert store.get_stats()["available"] is False
