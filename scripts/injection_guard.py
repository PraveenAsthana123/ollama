#!/usr/bin/env python3
"""
Real, but explicitly LIMITED, prompt-injection detector -- heuristic
pattern matching against well-known injection phrasings.

HONEST SCOPE, not oversold: this catches naive, blatant attempts
("ignore all previous instructions", "you are now DAN", literal
role-override markers). It does NOT catch obfuscated, translated,
encoded, or genuinely novel adversarial phrasing -- no regex-based
detector can. Pattern matching is a known-weak defense in the AI
security literature; this exists to (a) give real audit visibility into
the crudest attempts and (b) block the most blatant ones, not to claim
prompt injection is "solved" or "prevented." A caller relying on this as
the only defense for a system with real tool-execution consequences
would be making a mistake this module cannot correct for them.

Current real risk surface this actually protects: execution_gateway.py
is a single-shot generation call with no downstream tool-execution loop
that treats the OUTPUT as further instructions, so the practical impact
of a missed injection here is currently bounded to "the model was asked
to role-play something silly," not "an agent executed an unauthorized
action." If/when this repo's supervisor.py-driven task execution starts
consuming free-text model output as tool-call instructions, this module's
real protection value increases and its current scope should be revisited.
"""

from __future__ import annotations

import re

# Deliberately narrow and literal -- a broad/fuzzy pattern set produces
# false positives on legitimate text (e.g., "explain how prompt injection
# works" is a valid security-research question, not an attack).
_PATTERNS = [
    re.compile(r"\bignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+instructions?\b", re.I),
    re.compile(r"\bdisregard\s+(all\s+|any\s+)?(previous|prior|above|earlier|the\s+system)\s*(instructions?|prompt)?\b", re.I),
    re.compile(r"\byou\s+are\s+now\s+\w+", re.I),
    re.compile(r"\bnew\s+instructions?\s*:", re.I),
    re.compile(r"\bsystem\s*(prompt)?\s*override\b", re.I),
    re.compile(r"###\s*system\s*###", re.I),
    re.compile(r"\bforget\s+(everything|all)\s+(you\s+)?(know|were\s+told)\b", re.I),
    re.compile(r"\breveal\s+(your\s+)?(system\s+prompt|instructions)\b", re.I),
    re.compile(r"\bact\s+as\s+(if\s+you\s+have\s+)?no\s+(restrictions|rules|filters)\b", re.I),
]


def scan(text: str) -> dict:
    """Returns {"flagged": bool, "matched_patterns": [...]} -- never
    raises, never modifies the input. Caller decides what to do with a
    flag (log, block, escalate) -- this module only detects."""
    matched = [p.pattern for p in _PATTERNS if p.search(text)]
    return {"flagged": bool(matched), "matched_patterns": matched}
