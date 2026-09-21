import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.execution_gateway as gateway
import scripts.semantic_cache as semantic_cache


EVENTS = Path("/tmp/test_execution_gateway_events.jsonl")


@pytest.fixture(autouse=True)
def isolate_execution_gateway():
    """Every test gets a clean event log, no real exact-cache, and no real
    semantic-cache lookups by default -- tests that want to exercise the
    real semantic cache opt in explicitly instead of silently depending on
    real Qdrant/embedding state left over from another test."""
    gateway.EVENTS_PATH = EVENTS
    if EVENTS.exists():
        EVENTS.unlink()
    gateway._redis_client = None
    with patch.object(gateway.semantic_cache, "lookup", return_value=None), \
         patch.object(gateway.semantic_cache, "store"):
        yield


def test_executes_real_provider_and_logs_event():
    with patch.object(gateway, "_ollama_tags", return_value=["qwen3:1.7b"]), \
         patch.object(gateway, "_ollama_generate", return_value={"response": "56"}) as mock_gen:
        result = gateway.execute("What is 7 times 8?", kind="prose")

    assert result["decision"] == "inference"
    assert result["provider"] == "direct_ollama"
    assert result["response"] == "56"
    assert result["cache_hit"] is False
    mock_gen.assert_called_once()
    events = [line for line in EVENTS.read_text().splitlines() if line.strip()]
    assert len(events) == 1
    assert '"status":"completed"' in events[0]


def test_no_installed_models_blocks_honestly():
    with patch.object(gateway, "_ollama_tags", return_value=[]):
        result = gateway.execute("hello", kind="prose")

    assert result["decision"] == "blocked"
    assert result["reason"] == "no_eligible_provider"


def test_ollama_failure_reports_error_not_fabricated_response():
    with patch.object(gateway, "_ollama_tags", return_value=["qwen3:1.7b"]), \
         patch.object(gateway, "_ollama_generate", side_effect=TimeoutError("model timed out")):
        result = gateway.execute("hello", kind="prose")

    assert result["decision"] == "error"
    assert "timed out" in result["reason"]


def test_exact_cache_hit_skips_ollama_call():
    class FakeRedis:
        def __init__(self):
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def setex(self, key, ttl, value):
            self.store[key] = value

    fake_redis = FakeRedis()
    gateway._redis_client = fake_redis

    with patch.object(gateway, "_ollama_tags", return_value=["qwen3:1.7b"]), \
         patch.object(gateway, "_ollama_generate", return_value={"response": "56"}) as mock_gen:
        first = gateway.execute("What is 7 times 8?", kind="prose")
        assert first["cache_hit"] is False
        second = gateway.execute("What is 7 times 8?", kind="prose")

    assert second["cache_hit"] is True
    assert second["cache_type"] == "exact"
    assert second["response"] == "56"
    mock_gen.assert_called_once()  # the second call must not hit Ollama again


# --- Real semantic cache (real Qdrant, real Ollama embeddings) -----------
# These deliberately do NOT use the autouse mock -- they exercise the real
# path end to end, same discipline as test_gpu_scheduler.py's real-Redis
# concurrency tests. Each test uses a UUID-unique query so it can never
# collide with another test's or another run's stored vectors.

@pytest.fixture
def real_semantic_cache():
    with patch.object(gateway.semantic_cache, "lookup", wraps=semantic_cache.lookup), \
         patch.object(gateway.semantic_cache, "store", wraps=semantic_cache.store):
        yield


def _unique_multiplication() -> tuple[int, int]:
    # Two operands derived from a fresh UUID each call so distinct tests
    # (and distinct runs, since the Qdrant collection persists) never
    # produce near-duplicate arithmetic content that could collide with
    # each other in the vector index. A shared *text tag* prefix was tried
    # first and found NOT sufficient for this -- two questions that are
    # both "about 7 times 8" score >0.92 similar regardless of a prefix
    # tag, since the tag is a small fraction of the embedded content.
    n = uuid.uuid4().int
    return 11 + (n % 70), 11 + ((n // 70) % 70)


def test_real_semantic_cache_hits_on_reworded_near_duplicate(real_semantic_cache):
    a, b = _unique_multiplication()
    original = f"What is {a} times {b}?"
    reworded = f"What does {a} times {b} equal?"
    answer = str(a * b)

    with patch.object(gateway, "_ollama_tags", return_value=["qwen3:1.7b"]), \
         patch.object(gateway, "_ollama_generate", return_value={"response": answer}) as mock_gen:
        first = gateway.execute(original, kind="prose")
        second = gateway.execute(reworded, kind="prose")

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["cache_type"] == "semantic"
    assert second["response"] == answer
    assert second["similarity"] >= 0.92
    mock_gen.assert_called_once()  # the reworded near-duplicate must not hit Ollama again


def test_real_semantic_cache_misses_on_genuinely_different_query(real_semantic_cache):
    a, b = _unique_multiplication()
    q1 = f"What is {a} times {b}?"
    q2 = f"What is the population of the city of {uuid.uuid4().hex[:10]}stan?"

    with patch.object(gateway, "_ollama_tags", return_value=["qwen3:1.7b"]), \
         patch.object(gateway, "_ollama_generate", return_value={"response": "different answer"}) as mock_gen:
        gateway.execute(q1, kind="prose")
        second = gateway.execute(q2, kind="prose")

    assert second["cache_hit"] is False
    assert mock_gen.call_count == 2  # a genuinely different query must always regenerate
