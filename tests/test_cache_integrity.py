import scripts.cache_integrity as cache_integrity


def test_sign_and_verify_round_trip():
    payload = {"response": "56", "model": "qwen3:1.7b", "tier": "fast"}
    signature = cache_integrity.sign(payload)
    assert cache_integrity.verify(payload, signature) is True


def test_verify_rejects_a_tampered_payload():
    payload = {"response": "56", "model": "qwen3:1.7b", "tier": "fast"}
    signature = cache_integrity.sign(payload)
    tampered = {**payload, "response": "an attacker-controlled answer"}
    assert cache_integrity.verify(tampered, signature) is False


def test_verify_rejects_a_forged_signature():
    payload = {"response": "56", "model": "qwen3:1.7b", "tier": "fast"}
    assert cache_integrity.verify(payload, "0" * 64) is False


def test_verify_rejects_empty_signature():
    payload = {"response": "56", "model": "qwen3:1.7b", "tier": "fast"}
    assert cache_integrity.verify(payload, "") is False


def test_signature_is_order_independent_via_canonicalization():
    # dict key order must not change the signature -- callers may
    # reconstruct the payload dict with keys in a different order
    a = cache_integrity.sign({"response": "56", "model": "m", "tier": "fast"})
    b = cache_integrity.sign({"tier": "fast", "model": "m", "response": "56"})
    assert a == b
