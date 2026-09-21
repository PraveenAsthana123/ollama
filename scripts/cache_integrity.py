#!/usr/bin/env python3
"""
Real HMAC integrity signing for cached payloads -- closes the STRIDE
Tampering finding: "Cached responses (exact + semantic) -- a compromised
Redis/Qdrant could serve altered cached responses -- Unmitigated."

Threat model this addresses: Redis and Qdrant are trusted-network-boundary
services (loopback only) but have no application-layer authentication of
their own (a separate, still-open STRIDE Spoofing finding). If either
backend were compromised or its data directly edited on disk, a consumer
of this cache would have no way to detect that a cached response had been
altered from what was originally computed. HMAC signing means a tampered
payload is detected and rejected (treated as a cache miss, not silently
trusted) rather than served as if it were the real, original result.

Does NOT protect against: a compromise of the machine itself (the HMAC key
lives on the same filesystem as the cache backends -- this defends against
tampering with the cache stores specifically, not a full host compromise,
which is a different, larger threat this module doesn't claim to solve).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any

_KEY_PATH = Path.home() / ".local/state/ollama-control-tower/cache_hmac.key"
_key_cache: bytes | None = None


def _load_or_create_key() -> bytes:
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _KEY_PATH.exists():
        _key_cache = bytes.fromhex(_KEY_PATH.read_text().strip())
        return _key_cache
    key = secrets.token_bytes(32)
    fd = os.open(_KEY_PATH, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    try:
        os.write(fd, key.hex().encode())
    finally:
        os.close(fd)
    _key_cache = key
    return key


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(payload: dict[str, Any]) -> str:
    """Real HMAC-SHA256 over the canonical JSON encoding of payload."""
    key = _load_or_create_key()
    return hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()


def verify(payload: dict[str, Any], signature: str) -> bool:
    """Constant-time comparison -- never short-circuits on the first
    mismatched byte, which would leak timing information about the real
    signature to an attacker probing the cache backend directly."""
    if not signature:
        return False
    key = _load_or_create_key()
    expected = hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
