"""Unified recall system — single interface to all memory backends."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from functools import wraps
import threading

from .config import CozyConfig
from .libsql_store import Entity, LibSQLStore
from .qstash_store import QStashConfig, QStashStore
from .redis_store import RedisStore
from .search_store import SearchStore
from .sync import MemorySync
from .vector_store import VectorStore, VectorResult


class RateLimitExceeded(Exception):
    pass

def rate_limited(limit: int, window: int):
    """Decorator to limit method calls per instance based on sliding window."""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            now = time.time()
            with self._rate_limit_lock:
                # Clean up old timestamps
                while self._rate_limit_timestamps and self._rate_limit_timestamps[0] < now - window:
                    self._rate_limit_timestamps.pop(0)

                if len(self._rate_limit_timestamps) >= limit:
                    raise RateLimitExceeded(f"Rate limit exceeded for {func.__name__}()")

                self._rate_limit_timestamps.append(now)
            return func(self, *args, **kwargs)
        return wrapper
    return decorator

class RecallStrategy(Enum):
    """Which backend to query."""
    REDIS = "redis"         # Hot cache, <5ms
    VECTOR = "vector"       # Semantic search, ~50ms
    SEARCH = "search"       # Full-text keyword, ~50ms
    LIBSQL = "libsql"       # Local persistence
    AUTO = "auto"           # Let CozyMemory decide


@dataclass
class RecallResult:
    source: str
    id: str
    score: float
    content: str
    metadata: dict = field(default_factory=dict)


class CozyMemory:
    """Unified memory system. One interface, four backends.

    Usage:
        mem = CozyMemory()

        # Semantic recall
        results = mem.recall("What did we decide about TurboQuant?")

        # Exact keyword search
        results = mem.recall("FP8 KV cache", strategy=RecallStrategy.SEARCH)

        # Hot cache lookup
        entity = mem.recall("entity:turboquant", strategy=RecallStrategy.REDIS)

        # Store something
        mem.store("turboquant", type="project", description="KV cache compression research")

        # Sync everything
        mem.sync()
    """

    def __init__(self, config: CozyConfig | None = None):
        self.config = config or CozyConfig.from_env()
        self.redis = RedisStore(self.config.redis)
        self.vector = VectorStore(self.config.vector)
        self.search = SearchStore(vector_store=self.vector)
        self.libsql = LibSQLStore(self.config.libsql)
        self.qstash = QStashStore()
        self.sync = MemorySync(self.libsql, self.vector, self.redis)

        # Lock and state for local rate limiting (e.g. store method)
        self._rate_limit_lock = threading.Lock()
        self._rate_limit_timestamps = []

    # ── Core Recall ────────────────────────────────────────────

    def recall(
        self,
        query: str,
        strategy: RecallStrategy = RecallStrategy.AUTO,
        top_k: int = 5,
        namespace: str = "",
    ) -> list[RecallResult]:
        """Query memory. Strategy=AUTO picks the best backend based on query."""

        if strategy == RecallStrategy.AUTO:
            strategy = self._pick_strategy(query)

        if strategy == RecallStrategy.REDIS:
            return self._recall_redis(query, top_k)
        elif strategy == RecallStrategy.VECTOR:
            return self._recall_vector(query, top_k, namespace)
        elif strategy == RecallStrategy.SEARCH:
            return self._recall_search(query, top_k, namespace)
        elif strategy == RecallStrategy.LIBSQL:
            return self._recall_libsql(query, top_k)
        else:
            # Fallback: try all, merge results
            return self._recall_all(query, top_k, namespace)

    def _pick_strategy(self, query: str) -> RecallStrategy:
        """Heuristic strategy selection."""
        # Short exact-looking queries → Redis or Search
        if ":" in query and len(query.split()) <= 3:
            return RecallStrategy.REDIS
        # Quoted phrases or technical terms → Search
        if '"' in query or any(c in query for c in ["_", "-", "."]):
            return RecallStrategy.SEARCH
        # Default: semantic vector search
        return RecallStrategy.VECTOR

    def _recall_redis(self, key: str, top_k: int) -> list[RecallResult]:
        val = self.redis.get(key)
        if val is None:
            # Try pattern match
            keys = self.redis.keys(f"*{key}*")
            results = []
            for k in keys[:top_k]:
                v = self.redis.get(k)
                if v is not None:
                    results.append(RecallResult(
                        source="redis", id=k, score=1.0,
                        content=str(v) if isinstance(v, str) else str(v),
                    ))
            return results
        return [RecallResult(source="redis", id=key, score=1.0, content=str(val))]

    def _recall_vector(self, query: str, top_k: int, namespace: str) -> list[RecallResult]:
        try:
            results = self.vector.query(query, top_k=top_k, namespace=namespace)
            return [
                RecallResult(
                    source="vector", id=r.id, score=r.score,
                    content=r.metadata.get("name", r.id),
                    metadata=r.metadata,
                )
                for r in results
            ]
        except Exception:
            return []

    def _recall_search(self, query: str, top_k: int, namespace: str) -> list[RecallResult]:
        try:
            results = self.search.search(query, top_k=top_k, namespace=namespace)
            return [
                RecallResult(
                    source="search", id=r.id, score=r.score,
                    content=r.content,
                    metadata=r.metadata or {},
                )
                for r in results
            ]
        except Exception:
            return []

    def _recall_libsql(self, query: str, top_k: int) -> list[RecallResult]:
        entities = self.libsql.search_entities(query, limit=top_k)
        return [
            RecallResult(
                source="libsql", id=e.id, score=e.salience,
                content=f"{e.name}: {e.description}",
                metadata={"type": e.type, **e.metadata},
            )
            for e in entities
        ]

    def _recall_all(self, query: str, top_k: int, namespace: str) -> list[RecallResult]:
        """Query all backends and merge by score."""
        results = []
        results.extend(self._recall_redis(query, top_k))
        results.extend(self._recall_vector(query, top_k, namespace))
        results.extend(self._recall_search(query, top_k, namespace))
        results.extend(self._recall_libsql(query, top_k))
        # Deduplicate by ID, keep highest score
        seen: dict[str, RecallResult] = {}
        for r in results:
            if r.id not in seen or r.score > seen[r.id].score:
                seen[r.id] = r
        return sorted(seen.values(), key=lambda x: x.score, reverse=True)[:top_k]

    # ── Store ──────────────────────────────────────────────────

    @rate_limited(limit=10, window=60)
    def store(
        self,
        id: str,
        type: str,
        name: str = "",
        description: str = "",
        metadata: dict | None = None,
        sync_to_cloud: bool = True,
    ) -> Entity:
        """Store an entity in libSQL (truth) and optionally sync to Vector + Redis."""
        entity = self.libsql.upsert_entity(
            id=id,
            type=type,
            name=name or id,
            description=description,
            metadata=metadata,
        )
        if sync_to_cloud:
            self.sync.sync_entity_to_vector(id)
        return entity

    # ── Activity Tracking ──────────────────────────────────────

    def log_activity(self, activity: str, data: Any = None) -> None:
        """Log activity to Redis (hot) and libSQL (persistent)."""
        self.redis.log_activity(activity, data)
        self.libsql.log("activity", activity, {"data": data} if data else None)

    def recent_activity(self, count: int = 20) -> list[dict]:
        """Get recent activity from Redis cache."""
        return self.redis.recent_activity(count)

    # ── Dedup ──────────────────────────────────────────────────

    def already_done(self, key: str, ttl: int = 172800) -> bool:
        """Check if a task was already done (48h default).
        Returns True if already done (duplicate), False if new."""
        return not self.redis.dedup(key, ttl)

    # ── Rate Limiting ──────────────────────────────────────────

    def rate_limit(self, resource: str, limit: int, window: int = 60) -> dict:
        """Check rate limit for a resource."""
        return self.redis.rate_limit(resource, limit, window)

    # ── Health ──────────────────────────────────────────────────

    def health(self) -> dict:
        """Check all backend connectivity."""
        return {
            "redis": self.redis.ping(),
            "vector": self.vector.ping(),
            "search": self.search.ping(),
            "libsql": self.libsql.ping(),
            "qstash": self.qstash.ping(),
        }

    def stats(self) -> dict:
        """Get system stats."""
        return {
            "libsql": self.libsql.stats(),
            "redis": self.redis.info(),
        }
