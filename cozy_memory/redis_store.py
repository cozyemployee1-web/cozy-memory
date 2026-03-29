"""Upstash Redis backend — hot cache, queues, state, rate limiting."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from upstash_redis import Redis

from .config import RedisConfig


class RedisStore:
    """Fast key-value cache with TTL, queues, pub/sub, and rate limiting."""

    def __init__(self, config: RedisConfig | None = None):
        self.config = config or RedisConfig.from_env()
        self._redis: Redis | None = None

    @property
    def redis(self) -> Redis:
        if self._redis is None:
            self._redis = Redis(url=self.config.url, token=self.config.token)
        return self._redis

    def _key(self, key: str) -> str:
        return f"{self.config.prefix}{key}"

    # ── Core CRUD ──────────────────────────────────────────────

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set a value with optional TTL (seconds)."""
        ttl = ttl or self.config.default_ttl
        serialized = json.dumps(value) if not isinstance(value, str) else value
        self.redis.set(self._key(key), serialized, ex=ttl)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value, returning default if missing."""
        val = self.redis.get(self._key(key))
        if val is None:
            return default
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val

    def delete(self, key: str) -> bool:
        """Delete a key. Returns True if it existed."""
        return bool(self.redis.delete(self._key(key)))

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        return bool(self.redis.exists(self._key(key)))

    def keys(self, pattern: str = "*") -> list[str]:
        """List keys matching pattern (after prefix)."""
        raw_keys = self.redis.keys(self._key(pattern))
        prefix_len = len(self.config.prefix)
        return [k[prefix_len:] for k in raw_keys]

    # ── Session State ─────────────────────────────────────────

    def set_session(self, session_id: str, data: dict, ttl: int = 7200) -> None:
        """Store session state (default 2h TTL)."""
        self.set(f"session:{session_id}", data, ttl=ttl)

    def get_session(self, session_id: str) -> dict:
        """Get session state."""
        return self.get(f"session:{session_id}", {})

    def update_session(self, session_id: str, updates: dict) -> dict:
        """Merge updates into existing session state."""
        current = self.get_session(session_id)
        current.update(updates)
        self.set_session(session_id, current)
        return current

    # ── Deduplication ─────────────────────────────────────────

    def dedup(self, key: str, ttl: int = 172800) -> bool:
        """Check-and-set for deduplication. Returns True if NEW (first call).
        Returns False if duplicate (already seen within TTL window).
        Default TTL: 48 hours."""
        result = self.redis.set(self._key(f"dedup:{key}"), "1", ex=ttl, nx=True)
        return result is not None

    # ── Rate Limiting ─────────────────────────────────────────

    def rate_limit(self, resource: str, limit: int, window: int = 60) -> dict:
        """Sliding window rate limiter.
        Returns: {"allowed": bool, "current": int, "limit": int, "reset_in": int}"""
        key = self._key(f"rate:{resource}")
        now = int(time.time())
        window_start = now - window

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)  # clean old
        pipe.zadd(key, {str(now): now})  # add current
        pipe.zcard(key)  # count
        pipe.expire(key, window)  # TTL
        results = pipe.exec()

        count = results[2] if results else 0
        return {
            "allowed": count <= limit,
            "current": count,
            "limit": limit,
            "reset_in": window,
        }

    # ── Queues ─────────────────────────────────────────────────

    def enqueue(self, queue: str, item: Any) -> int:
        """Push item to a queue. Returns new queue length."""
        serialized = json.dumps(item)
        return self.redis.rpush(self._key(f"queue:{queue}"), serialized)

    def dequeue(self, queue: str, timeout: int = 0) -> Any | None:
        """Pop item from queue. Blocks up to timeout seconds (0 = non-blocking)."""
        if timeout > 0:
            result = self.redis.blpop(self._key(f"queue:{queue}"), timeout=timeout)
            if result:
                _, val = result
                return json.loads(val)
            return None
        val = self.redis.lpop(self._key(f"queue:{queue}"))
        return json.loads(val) if val else None

    def queue_length(self, queue: str) -> int:
        return self.redis.llen(self._key(f"queue:{queue}"))

    # ── Recent Activity Log ───────────────────────────────────

    def log_activity(self, activity: str, data: Any = None, max_len: int = 100) -> None:
        """Append to recent activity log (capped list)."""
        entry = json.dumps({"ts": time.time(), "activity": activity, "data": data})
        key = self._key("activity:recent")
        self.redis.lpush(key, entry)
        self.redis.ltrim(key, 0, max_len - 1)

    def recent_activity(self, count: int = 20) -> list[dict]:
        """Get recent activity entries."""
        entries = self.redis.lrange(self._key("activity:recent"), 0, count - 1)
        return [json.loads(e) for e in entries]

    # ── Pub/Sub (simplified) ──────────────────────────────────

    def publish(self, channel: str, message: Any) -> int:
        """Publish message to channel. Returns number of receivers."""
        return self.redis.publish(self._key(f"pub:{channel}"), json.dumps(message))

    # ── Health ─────────────────────────────────────────────────

    def ping(self) -> bool:
        """Check Redis connectivity."""
        try:
            return self.redis.ping()
        except Exception:
            return False

    def info(self) -> dict:
        """Get basic Redis info."""
        return {
            "connected": self.ping(),
            "prefix": self.config.prefix,
        }
