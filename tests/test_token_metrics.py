from scripts.token_metrics import aggregate, reaction
from scripts.token_router import compress_observation, duplicate_ratio


def test_observation_compression_deduplicates_and_keeps_failures():
    observation = "\n".join(["progress"] * 30 + ["ERROR test failed", "Traceback: bad call"])
    result = compress_observation(observation, 20)
    assert result.count("progress") == 1
    assert "ERROR test failed" in result
    assert duplicate_ratio(observation) > 0.8


def test_token_metrics_group_and_react():
    events = [{
        "category": "model", "status": "completed", "agent_id": "coder", "task_id": "t1",
        "model": "cloud-strong", "provider": "cloud", "tool": "shell", "mcp_server": "terminal",
        "input_tokens": 100, "output_tokens": 20, "cached_tokens": 0, "compressed_tokens": 25,
        "duplicate_context_ratio": 0.3, "context_utilization": 0.9, "cost_usd": 0.01,
    } for _ in range(10)]
    result = aggregate(events)
    assert result["tokens_by_agent"] == {"coder": 1200}
    assert result["tokens_by_mcp"] == {"terminal": 1200}
    assert result["compressed_tokens"] == 250
    assert reaction(result) == ["deduplicate_and_prune", "summarize_or_compress", "enable_semantic_cache", "route_easy_tasks_local"]
