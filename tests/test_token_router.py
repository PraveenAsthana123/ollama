from scripts.token_router import choose_route, estimate_tokens, prepare


def test_log_pruning_keeps_error_and_reduces_context():
    context = "\n".join([f"INFO request {i} ok" for i in range(300)] + [
        "ERROR database timeout while saving invoice",
        "Traceback: connection pool exhausted",
    ])
    result = prepare("find the database timeout", context, "logs", 120)
    assert result.estimated_input_tokens_after <= 120
    assert "ERROR database timeout" in result.context
    assert result.compression_ratio < 0.25


def test_source_routes_to_code_and_has_bounded_output():
    result = prepare("fix this function", "def broken():\n    return missing", "source", 500)
    assert result.route == "code"
    assert result.output_limit_tokens == 1024
    assert len(result.cache_key) == 64


def test_brief_request_caps_output():
    result = prepare("answer briefly", "small context", "prose", 500)
    assert result.route == "fast"
    assert result.output_limit_tokens == 128


def test_token_estimate_is_conservative_and_stable():
    assert estimate_tokens("1234567") == 2
    assert choose_route("security architecture review", 100, "prose") == "strong"
