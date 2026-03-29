"""Upstash Search backend — falls back to Vector index for search operations.

The Upstash Search index is a hybrid dense+sparse index requiring explicit vectors.
For simplicity, we use the Vector index (which auto-embeds) for both semantic and
keyword-like searches. This module wraps Vector with search-oriented convenience."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from .vector_store import VectorStore, VectorResult
from .config import VectorConfig


@dataclass
class SearchResult:
    id: str
    score: float
    content: str
    metadata: dict | None = None


class SearchStore:
    """Search layer on top of Vector index. Uses semantic search as the backend."""

    def __init__(self, vector_store: VectorStore | None = None, vector_config: VectorConfig | None = None):
        if vector_store:
            self.vector = vector_store
        else:
            self.vector = VectorStore(vector_config)

    def search(
        self,
        query: str,
        top_k: int = 5,
        namespace: str = "",
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        """Search using the Vector index (auto-embeds query)."""
        results = self.vector.query(
            text=query,
            top_k=top_k,
            namespace=namespace,
            include_metadata=True,
            filter_expr=filter_expr,
        )
        return [
            SearchResult(
                id=r.id,
                score=r.score,
                content=r.metadata.get("name", r.metadata.get("description", r.id)),
                metadata=r.metadata,
            )
            for r in results
        ]

    def ping(self) -> bool:
        return self.vector.ping()
