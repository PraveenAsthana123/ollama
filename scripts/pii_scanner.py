#!/usr/bin/env python3
"""
Real PII scanner for free text -- closes the STRIDE Information Disclosure
finding: "Cached responses ... No PII-scrubbing on what gets cached" and
"redact() only redacts by dict key name ... does not scan the response
field's actual text content."

Design decision, and why: this module does NOT mask/redact PII out of the
response returned to the caller -- the caller asked a real question and
deserves the real answer. What it does instead is flag PII-containing
exchanges so execution_gateway.py can (a) skip caching them entirely (never
persisted to Redis/Qdrant, closing the real STRIDE gap) and (b) log a real
security event for visibility, without corrupting the actual answer with
masked-out text. Masking cached content would defeat the cache's purpose
(a "hit" that returns [REDACTED] instead of the real prior answer is not a
functioning cache) while doing nothing to protect the original response
already delivered to the caller in the same request.

HONEST SCOPE: regex-based PII detection has real, known limits -- it
catches structured PII (email, phone, SSN, credit-card-shaped numbers) and
nothing unstructured (names, addresses, "my daughter's school is..."). The
credit-card check includes a real Luhn checksum specifically to cut down
false positives on random 16-digit-shaped numbers (order IDs, tracking
numbers) that aren't actually valid card numbers.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# Requires at least one real separator (space/dot/hyphen/parens) somewhere
# in the match -- a bare, undelimited 10-digit run (a math result, an
# order ID, a tracking number) is NOT a phone number by convention, and an
# earlier version of this regex with every separator optional flagged
# exactly that: a real Luhn-unrelated 10-digit multiplication answer
# false-positived as "phone" purely because \d{10} alone satisfied every
# optional group. Real phone numbers are visually delimited or announced
# as phone numbers in context; requiring a separator is a deliberate
# precision/recall tradeoff, same family of fix as the credit-card Luhn
# check.
_PHONE = re.compile(
    r"\b(?:\+?1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"
)
# Candidate 13-19 digit sequences, optionally separated by spaces/hyphens --
# validated against Luhn below, not trusted on shape alone.
_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn_valid(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def scan(text: str) -> dict:
    """Returns {"flagged": bool, "types": [...]} -- never raises, never
    modifies input. Caller decides what to do with a flag."""
    types = []
    if _EMAIL.search(text):
        types.append("email")
    if _SSN.search(text):
        types.append("ssn")
    if _PHONE.search(text):
        types.append("phone")
    for candidate in _CARD_CANDIDATE.findall(text):
        digits = re.sub(r"[ -]", "", candidate)
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            types.append("credit_card")
            break
    return {"flagged": bool(types), "types": types}
