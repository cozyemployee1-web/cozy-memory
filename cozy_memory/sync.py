"""Sync layer — keep backends in sync."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .libsql_store import LibSQLStore
    from .redis_store import RedisStore
    from .vector_store import VectorStore


class MemorySync:
    """Bidirectional sync between libSQL (truth) and Upstash Vector (cloud)."""

    def __init__(
        self,
        libsql: LibSQLStore,
        vector: VectorStore,
        redis: RedisStore,
        namespace: str = "memory",
    ):
        self.libsql = libsql
        self.vector = vector
        self.redis = redis
        self.namespace = namespace

    def sync_entity_to_vector(self, entity_id: str) -> dict:
        """Sync a single entity from libSQL to Upstash Vector."""
        entity = self.libsql.get_entity(entity_id)
        if not entity:
            return {"status": "not_found", "id": entity_id}

        # Build searchable text from entity
        data = f"{entity.name}: {entity.description}"
        metadata = {
            "type": entity.type,
            "name": entity.name,
            "salience": entity.salience,
            **entity.metadata,
        }

        self.vector.upsert(
            id=entity.id,
            data=data,
            metadata=metadata,
            namespace=self.namespace,
        )

        # Cache in Redis for fast lookup
        self.redis.set(
            f"entity:{entity.id}",
            {"name": entity.name, "type": entity.type, "description": entity.description},
            ttl=86400,  # 24h cache
        )

        return {"status": "synced", "id": entity.id}

    def sync_all_entities(self) -> dict:
        """Full sync: all libSQL entities → Vector + Redis."""
        entities = self.libsql.list_entities(limit=10000)
        synced = 0
        failed = 0

        # Batch upsert to Vector
        batch = []
        for entity in entities:
            data = f"{entity.name}: {entity.description}"
            metadata = {
                "type": entity.type,
                "name": entity.name,
                "salience": entity.salience,
                **entity.metadata,
            }
            batch.append({
                "id": entity.id,
                "data": data,
                "metadata": metadata,
                "namespace": self.namespace,
            })

        if batch:
            try:
                self.vector.upsert_batch(batch)
                synced = len(batch)
            except Exception as e:
                # Fall back to individual upserts
                for entry in batch:
                    try:
                        self.vector.upsert(
                            id=entry["id"],
                            data=entry["data"],
                            metadata=entry["metadata"],
                            namespace=entry["namespace"],
                        )
                        synced += 1
                    except Exception:
                        failed += 1

        # Update Redis cache
        for entity in entities:
            self.redis.set(
                f"entity:{entity.id}",
                {"name": entity.name, "type": entity.type, "description": entity.description},
                ttl=86400,
            )

        return {"synced": synced, "failed": failed, "total": len(entities)}

    def invalidate_cache(self, entity_id: str) -> None:
        """Invalidate Redis cache for an entity."""
        self.redis.delete(f"entity:{entity_id}")
