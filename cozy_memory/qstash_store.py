"""Upstash QStash backend — guaranteed message delivery with retries."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx


@dataclass
class QStashConfig:
    url: str = ""
    token: str = ""
    signing_key: str = ""

    @classmethod
    def from_env(cls) -> QStashConfig:
        import os
        return cls(
            url=os.environ.get("QSTASH_URL", "https://qstash.upstash.io"),
            token=os.environ.get("QSTASH_TOKEN", ""),
            signing_key=os.environ.get("QSTASH_SIGNING_KEY", ""),
        )


@dataclass
class PublishResult:
    message_id: str
    url: str
    deduplicated: bool = False


class QStashStore:
    """Serverless message queue with guaranteed delivery and auto-retries.

    Use cases:
    - Dispatch sub-agent tasks (guaranteed delivery even on connection drops)
    - Send research results back to memory/Telegram (no lost findings)
    - Schedule delayed messages (reminders, follow-ups)
    - Fan-out tasks to multiple consumers
    """

    def __init__(self, config: QStashConfig | None = None):
        self.config = config or QStashConfig.from_env()
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.config.url,
                headers={
                    "Authorization": f"Bearer {self.config.token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    # ── Publish Messages ───────────────────────────────────────

    def publish(
        self,
        url: str,
        body: Any = None,
        headers: dict | None = None,
        retries: int = 3,
        delay: int | None = None,
        dedup_id: str | None = None,
        callback: str | None = None,
        failure_callback: str | None = None,
    ) -> dict:
        """Publish a message for guaranteed delivery to a URL.

        Args:
            url: Destination URL (HTTPS endpoint to deliver to)
            body: Message body (dict auto-serialized to JSON)
            headers: Custom headers to include in delivery
            retries: Max retry attempts (default 3)
            delay: Delay in seconds before first delivery
            dedup_id: Deduplication ID (prevents duplicate deliveries)
            callback: URL to call on successful delivery
            failure_callback: URL to call after all retries exhausted
        """
        payload: dict[str, Any] = {"destination": url}

        if body is not None:
            payload["body"] = json.dumps(body) if isinstance(body, (dict, list)) else str(body)

        if headers:
            payload["headers"] = headers

        if retries != 3:
            payload["retries"] = retries

        if delay is not None:
            payload["delay"] = delay

        if dedup_id:
            payload["deduplicationId"] = dedup_id

        if callback:
            payload["callback"] = callback

        if failure_callback:
            payload["failureCallback"] = failure_callback

        resp = self.client.post("/v2/publish", json=payload)
        resp.raise_for_status()
        return resp.json()

    def publish_json(
        self,
        url: str,
        data: Any,
        retries: int = 3,
        dedup_id: str | None = None,
    ) -> dict:
        """Convenience: publish JSON data to a URL."""
        return self.publish(
            url=url,
            body=data,
            headers={"Content-Type": "application/json"},
            retries=retries,
            dedup_id=dedup_id,
        )

    def enqueue(
        self,
        queue_name: str,
        url: str,
        body: Any = None,
        retries: int = 3,
        dedup_id: str | None = None,
    ) -> dict:
        """Publish to a named queue (FIFO delivery within queue)."""
        payload: dict[str, Any] = {
            "destination": url,
            "queueName": queue_name,
        }
        if body is not None:
            payload["body"] = json.dumps(body) if isinstance(body, (dict, list)) else str(body)
        if retries != 3:
            payload["retries"] = retries
        if dedup_id:
            payload["deduplicationId"] = dedup_id

        resp = self.client.post("/v2/publish", json=payload)
        resp.raise_for_status()
        return resp.json()

    # ── Scheduling ─────────────────────────────────────────────

    def schedule(
        self,
        url: str,
        body: Any = None,
        cron: str | None = None,
        delay: int | None = None,
        retries: int = 3,
    ) -> dict:
        """Create a scheduled message (cron or one-time delay).

        Args:
            url: Destination URL
            body: Message body
            cron: Cron expression (e.g., "0 3 * * *" for daily 3 AM)
            delay: One-time delay in seconds
            retries: Max retry attempts
        """
        payload: dict[str, Any] = {"destination": url}

        if body is not None:
            payload["body"] = json.dumps(body) if isinstance(body, (dict, list)) else str(body)

        if cron:
            payload["cron"] = cron
        if delay is not None:
            payload["delay"] = delay
        if retries != 3:
            payload["retries"] = retries

        resp = self.client.post("/v2/schedules", json=payload)
        resp.raise_for_status()
        return resp.json()

    def get_schedule(self, schedule_id: str) -> dict:
        """Get schedule details."""
        resp = self.client.get(f"/v2/schedules/{schedule_id}")
        resp.raise_for_status()
        return resp.json()

    def list_schedules(self) -> list[dict]:
        """List all schedules."""
        resp = self.client.get("/v2/schedules")
        resp.raise_for_status()
        return resp.json()

    def delete_schedule(self, schedule_id: str) -> dict:
        """Delete a schedule."""
        resp = self.client.delete(f"/v2/schedules/{schedule_id}")
        resp.raise_for_status()
        return resp.json()

    # ── Messages ───────────────────────────────────────────────

    def get_message(self, message_id: str) -> dict:
        """Get message details and delivery status."""
        resp = self.client.get(f"/v2/messages/{message_id}")
        resp.raise_for_status()
        return resp.json()

    def cancel_message(self, message_id: str) -> dict:
        """Cancel a pending message."""
        resp = self.client.delete(f"/v2/messages/{message_id}")
        resp.raise_for_status()
        return resp.json()

    # ── Events (DLQ) ───────────────────────────────────────────

    def list_events(
        self,
        message_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List delivery events (for monitoring retries and failures).

        States: CREATED, DELIVERED, ERROR, ACTIVE, RETRY
        """
        params: dict[str, Any] = {"limit": limit}
        if message_id:
            params["filter.messageId"] = message_id
        if state:
            params["filter.state"] = state

        resp = self.client.get("/v2/events", params=params)
        resp.raise_for_status()
        return resp.json().get("events", [])

    # ── Utility ────────────────────────────────────────────────

    def make_dedup_id(self, *parts: str) -> str:
        """Generate a deterministic deduplication ID from parts."""
        combined = "::".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:32]

    def ping(self) -> bool:
        """Check QStash connectivity."""
        try:
            resp = self.client.get("/v2/events", params={"limit": 1})
            return resp.status_code < 500
        except Exception:
            return False
