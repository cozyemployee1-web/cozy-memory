"""Upstash Vector backend — semantic search with built-in embeddings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import httpx

from .config import VectorConfig


@dataclass
class VectorResult:
    id: str
    score: float
    metadata: dict
    data: str | None = None


class VectorStore:
    """Semantic memory using Upstash Vector with built-in BGE embeddings."""

    def __init__(self, config: VectorConfig | None = None):
        self.config = config or VectorConfig.from_env()
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

    def upsert(
        self,
        id: str,
        data: str,
        metadata: dict | None = None,
        namespace: str = "",
    ) -> dict:
        """Insert or update a vector entry.
        Upstash auto-embeds the data string using BGE_LARGE_EN_V1_5."""
        payload = {
            "id": id,
            "data": data,
        }
        if metadata:
            payload["metadata"] = metadata
        if namespace:
            payload["namespace"] = namespace

        resp = self.client.post("/vectors/upsert", json={"vectors": [payload]})
        resp.raise_for_status()
        return resp.json()

    def upsert_batch(
        self,
        entries: list[dict],
        namespace: str = "",
    ) -> dict:
        """Batch upsert. Each entry: {id, data, metadata?}."""
        for e in entries:
            if namespace:
                e["namespace"] = namespace
        resp = self.client.post("/vectors/upsert", json={"vectors": entries})
        resp.raise_for_status()
        return resp.json()

    def query(
        self,
        text: str,
        top_k: int = 5,
        namespace: str = "",
        include_metadata: bool = True,
        include_data: bool = False,
        filter_expr: str | None = None,
    ) -> list[VectorResult]:
        """Semantic search. Text is auto-embedded."""
        payload = {
            "data": text,
            "topK": top_k,
            "includeMetadata": include_metadata,
            "includeData": include_data,
        }
        if namespace:
            payload["namespace"] = namespace
        if filter_expr:
            payload["filter"] = filter_expr

        resp = self.client.post("/query", json=payload)
        resp.raise_for_status()
        results = resp.json().get("result", [])

        return [
            VectorResult(
                id=r["id"],
                score=r.get("score", 0.0),
                metadata=r.get("metadata", {}),
                data=r.get("data"),
            )
            for r in results
        ]

    def fetch(self, id: str, namespace: str = "") -> dict | None:
        """Fetch a specific vector by ID."""
        payload = {"ids": [id]}
        if namespace:
            payload["namespace"] = namespace
        resp = self.client.post("/vectors/fetch", json=payload)
        resp.raise_for_status()
        vectors = resp.json().get("vectors", [])
        return vectors[0] if vectors else None

    def delete(self, id: str, namespace: str = "") -> dict:
        """Delete a vector by ID."""
        payload = {"ids": [id]}
        if namespace:
            payload["namespace"] = namespace
        resp = self.client.post("/vectors/delete", json=payload)
        resp.raise_for_status()
        return resp.json()

    def delete_namespace(self, namespace: str) -> dict:
        """Delete an entire namespace."""
        resp = self.client.post("/vectors/delete", json={"namespace": namespace, "deleteAll": True})
        resp.raise_for_status()
        return resp.json()

    def list_namespaces(self) -> list[str]:
        """List all namespaces."""
        resp = self.client.post("/vectors/list-namespaces", json={})
        resp.raise_for_status()
        return resp.json().get("namespaces", [])

    def info(self) -> dict:
        """Get index info."""
        resp = self.client.get("/info")
        resp.raise_for_status()
        return resp.json()

    def ping(self) -> bool:
        try:
            self.info()
            return True
        except Exception:
            return False
