from pathlib import Path
from unittest.mock import patch

import scripts.execution_gateway as gateway


EVENTS = Path("/tmp/test_execution_gateway_events.jsonl")


def setup_function():
    gateway.EVENTS_PATH = EVENTS
    if EVENTS.exists():
        EVENTS.unlink()
    gateway._redis_client = None  # deterministic: exercise the no-cache path unless a test opts in


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
    assert second["response"] == "56"
    mock_gen.assert_called_once()  # the second call must not hit Ollama again
