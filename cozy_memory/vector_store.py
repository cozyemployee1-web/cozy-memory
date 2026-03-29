"""Upstash Vector backend — semantic search with built-in embeddings using SDK."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from upstash_vector import Index

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
        self._index: Index | None = None

    @property
    def index(self) -> Index:
        if self._index is None:
            self._index = Index(url=self.config.url, token=self.config.token)
        return self._index

    def upsert(
        self,
        id: str,
        data: str,
        metadata: dict | None = None,
        namespace: str = "",
    ) -> dict:
        """Insert or update a vector entry.
        Upstash auto-embeds the data string using BGE_LARGE_EN_V1_5."""
        kwargs = {"vectors": [(id, data, metadata or {})]}
        if namespace:
            kwargs["namespace"] = namespace
        result = self.index.upsert(**kwargs)
        return {"status": "ok", "result": str(result)}

    def upsert_batch(
        self,
        entries: list[dict],
        namespace: str = "",
    ) -> dict:
        """Batch upsert. Each entry: {id, data, metadata?}."""
        vectors = []
        for e in entries:
            vectors.append((e["id"], e["data"], e.get("metadata", {})))
        kwargs = {"vectors": vectors}
        if namespace:
            kwargs["namespace"] = namespace
        result = self.index.upsert(**kwargs)
        return {"status": "ok", "count": len(vectors), "result": str(result)}

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
        kwargs = {
            "data": text,
            "top_k": top_k,
            "include_metadata": include_metadata,
            "include_data": include_data,
        }
        if namespace:
            kwargs["namespace"] = namespace
        if filter_expr:
            kwargs["filter"] = filter_expr

        results = self.index.query(**kwargs)
        return [
            VectorResult(
                id=r.id,
                score=r.score,
                metadata=r.metadata or {},
                data=r.data,
            )
            for r in results
        ]

    def fetch(self, id: str, namespace: str = "") -> dict | None:
        """Fetch a specific vector by ID."""
        kwargs = {"ids": [id]}
        if namespace:
            kwargs["namespace"] = namespace
        results = self.index.fetch(**kwargs)
        if results:
            r = results[0]
            return {"id": r.id, "metadata": r.metadata, "data": r.data}
        return None

    def delete(self, id: str, namespace: str = "") -> dict:
        """Delete a vector by ID."""
        kwargs = {"ids": [id]}
        if namespace:
            kwargs["namespace"] = namespace
        result = self.index.delete(**kwargs)
        return {"status": "ok", "result": str(result)}

    def delete_namespace(self, namespace: str) -> dict:
        """Delete an entire namespace."""
        result = self.index.delete(namespace=namespace, delete_all=True)
        return {"status": "ok", "result": str(result)}

    def info(self) -> dict:
        """Get index info."""
        try:
            info = self.index.info()
            return {"status": "ok", "info": str(info)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def ping(self) -> bool:
        try:
            self.index.info()
            return True
        except Exception:
            return False
