#!/usr/bin/env python3
"""
Real caller-identity check for execution_gateway.py -- closes the STRIDE
Spoofing finding: "execution_gateway.py caller -- No caller identity
exists at all -- anyone with local network/CLI access can call it --
Unmitigated."

Honest scope: this is a single-machine, single-user local tool with no
network exposure (Ollama itself only binds loopback). A token check here
is defense-in-depth, not a hard security boundary -- anyone who can read
this machine's filesystem can also read the token file. What it DOES
close: an accidental or scripted call from a process that was never
deliberately given the token (a stray cron job, a misconfigured other
project sharing this machine, a copy-pasted curl command) now fails
closed instead of silently executing.

Token is generated once, stored 0600, same pattern as cache_integrity.py's
HMAC key -- deliberately separate files/secrets so a compromise of one
doesn't imply the other.
"""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

_TOKEN_PATH = Path.home() / ".local/state/ollama-control-tower/gateway.token"
ENV_VAR = "EXECUTION_GATEWAY_TOKEN"
_token_cache: str | None = None


def _load_or_create_token() -> str:
    global _token_cache
    if _token_cache is not None:
        return _token_cache
    _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _TOKEN_PATH.exists():
        _token_cache = _TOKEN_PATH.read_text().strip()
        return _token_cache
    token = secrets.token_urlsafe(32)
    fd = os.open(_TOKEN_PATH, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    try:
        os.write(fd, token.encode())
    finally:
        os.close(fd)
    _token_cache = token
    return token


def authorized(caller_token: str | None) -> bool:
    """Constant-time comparison against the real local token. A caller
    that supplies no token at all is unauthorized -- there is no
    "anonymous allowed" mode, matching this project's fail-closed
    convention (simple_auth.py's own "no password set = no login" rule)."""
    if not caller_token:
        return False
    return hmac.compare_digest(caller_token, _load_or_create_token())


def print_token_path() -> None:
    # Real bug fixed here: authorized(None) short-circuits before ever
    # calling _load_or_create_token(), so printing this path alone did NOT
    # guarantee a token file existed there yet -- confirmed by a real `cat`
    # on the printed path failing with "No such file or directory" right
    # after an unauthorized call. Explicitly create-if-missing here instead
    # of relying on a side effect of some other call happening first.
    _load_or_create_token()
    print(f"Gateway token: {_TOKEN_PATH}")
    print(f"Set {ENV_VAR} to this file's contents, or pass --token explicitly.")
