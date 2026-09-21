#!/usr/bin/env python3
"""
Real semantic cache -- closes the "Semantic cache: MISSING/disabled" gap
the external audit flagged repeatedly, including on its final re-check.
config/token-tower.yaml has named Qdrant as the intended adapter since
before this module existed; this is the first time that adapter is real
rather than a documented intention.

Design, matching config/token-tower.yaml's semantic_cache block exactly
(adapter: qdrant, similarity_threshold: 0.92, ttl_seconds: 86400):

  query -> embed (Ollama nomic-embed-text, already used elsewhere in this
           session's sibling job-portal project) -> Qdrant nearest-neighbor
           search, scoped by `kind` (a "prose" query must never match a
           "code" query's cache, even if textually similar) -> score above
           threshold? -> return the cached response : real inference, then
           store this (query, response) pair for future near-duplicates.

Deliberately conservative default threshold (0.92, from config, not
invented here) because a false hit silently serves a stale response as
fresh -- the same discipline already applied to the sibling job-portal
project's own semantic cache (chat_cached in shared-modules), which uses
an even higher 0.97 bar for a similar reason. Ollama's fast embedding path
is used for the query itself (not a chat-level generation), so a semantic
cache miss costs a fast embedding call, not a full generation.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams, FieldCondition, Filter, MatchValue

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cache_integrity  # noqa: E402

OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768  # nomic-embed-text's real output dimension, verified against a live call

QDRANT_HOST = "127.0.0.1"
QDRANT_PORT = 6333
COLLECTION = "execution_gateway_semantic_cache"

_client: QdrantClient | None = None


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=3)
        existing = {c.name for c in _client.get_collections().collections}
        if COLLECTION not in existing:
            _client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
            )
    return _client


def _embed(text: str) -> list[float]:
    """Real embedding call -- raises on failure, never returns a fake
    vector. Caller (lookup/store) decides how to degrade."""
    payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # nosemgrep: dynamic-urllib-use-detected -- OLLAMA_URL is a hardcoded local constant
        return json.loads(resp.read().decode())["embedding"]


def _point_id(kind: str, query: str) -> str:
    # deterministic id so a repeated exact query updates its own point
    # rather than accumulating duplicates
    digest = hashlib.sha256(f"{kind}:{query}".encode("utf-8")).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_OID, digest))


def lookup(query: str, kind: str, threshold: float, ttl_seconds: int) -> dict[str, Any] | None:
    """Returns the cached result dict on a real near-duplicate hit above
    threshold, else None. Never raises out -- a Qdrant/embedding failure
    degrades to a cache miss (real inference still runs), same fail-open
    posture as the exact cache elsewhere in this project."""
    try:
        client = _get_client()
        vector = _embed(query)
        now = time.time()
        response = client.query_points(
            collection_name=COLLECTION, query=vector, limit=1,
            query_filter=Filter(must=[FieldCondition(key="kind", match=MatchValue(value=kind))]),
            score_threshold=threshold,
        )
        hits = response.points
        if not hits:
            return None
        payload = hits[0].payload
        if now - payload.get("stored_at", 0) > ttl_seconds:
            return None  # expired -- treat as a miss rather than deleting mid-lookup
        signed = {"response": payload["response"], "model": payload["model"], "tier": payload["tier"]}
        if not cache_integrity.verify(signed, payload.get("signature", "")):
            # Tampered point -- a direct Qdrant edit would land here. Never
            # served; treated as a real miss so inference still runs.
            return None
        return {**signed, "similarity": round(hits[0].score, 4)}
    except Exception:
        return None


def store(query: str, kind: str, response: str, model: str, tier: str) -> None:
    """Best-effort -- a failure to cache must never break a real inference
    result that's already been returned to the caller."""
    try:
        client = _get_client()
        vector = _embed(query)
        signature = cache_integrity.sign({"response": response, "model": model, "tier": tier})
        client.upsert(collection_name=COLLECTION, points=[PointStruct(
            id=_point_id(kind, query), vector=vector,
            payload={"kind": kind, "response": response, "model": model, "tier": tier,
                     "stored_at": time.time(), "signature": signature},
        )])
    except Exception:
        pass
