"""Cozy Memory — Unified memory system for AI agents.

Four backends, one interface:
- Upstash Redis: hot cache, queues, rate limiting (~5ms)
- Upstash Vector: semantic search with built-in BGE embeddings (~50ms)
- Upstash Search: full-text keyword search (~50ms)
- libSQL: local persistence, source of truth

Usage:
    from cozy_memory import CozyMemory, RecallStrategy

    mem = CozyMemory()

    # Semantic recall (auto-selects Vector)
    results = mem.recall("What did we decide about TurboQuant?")

    # Exact keyword search
    results = mem.recall("FP8 KV cache", strategy=RecallStrategy.SEARCH)

    # Hot cache
    val = mem.recall("entity:turboquant", strategy=RecallStrategy.REDIS)

    # Store
    mem.store("turboquant", type="project", description="KV cache compression")

    # Sync libSQL → Vector + Redis
    mem.sync.sync_all_entities()
"""

from .config import CozyConfig, LibSQLConfig, RedisConfig, SearchConfig, VectorConfig
from .libsql_store import Entity, LibSQLStore
from .qstash_store import QStashConfig, QStashStore
from .redis_store import RedisStore
from .search_store import SearchResult, SearchStore
from .sync import MemorySync
from .unified import CozyMemory, RecallResult, RecallStrategy
from .vector_store import VectorResult, VectorStore

__version__ = "0.1.0"

__all__ = [
    "CozyMemory",
    "CozyConfig",
    "RecallStrategy",
    "RecallResult",
    "RedisStore",
    "RedisConfig",
    "VectorStore",
    "VectorConfig",
    "VectorResult",
    "SearchStore",
    "SearchConfig",
    "SearchResult",
    "LibSQLStore",
    "LibSQLConfig",
    "QStashStore",
    "QStashConfig",
    "Entity",
    "MemorySync",
]
