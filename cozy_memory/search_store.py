"""Upstash Search backend — full-text keyword search on vector data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import httpx

from .config import SearchConfig


@dataclass
class SearchResult:
    id: str
    score: float
    content: str
    metadata: dict | None = None


class SearchStore:
    """Full-text search on top of Upstash Vector data."""

    def __init__(self, config: SearchConfig | None = None):
        self.config = config or SearchConfig.from_env()
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

    def search(
        self,
        query: str,
        top_k: int = 5,
        namespace: str = "",
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        """Full-text search with keyword matching."""
        payload = {
            "query": query,
            "topK": top_k,
        }
        if namespace:
            payload["namespace"] = namespace
        if filter_expr:
            payload["filter"] = filter_expr

        resp = self.client.post("/search", json=payload)
        resp.raise_for_status()
        results = resp.json().get("result", [])

        return [
            SearchResult(
                id=r["id"],
                score=r.get("score", 0.0),
                content=r.get("content", ""),
                metadata=r.get("metadata"),
            )
            for r in results
        ]

    def ping(self) -> bool:
        try:
            resp = self.client.post("/search", json={"query": "test", "topK": 1})
            return resp.status_code < 500
        except Exception:
            return False
