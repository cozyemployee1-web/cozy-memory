"""Configuration for Cozy Memory system."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RedisConfig:
    url: str = ""
    token: str = ""
    prefix: str = "cozy:"
    default_ttl: int = 3600  # 1 hour

    @classmethod
    def from_env(cls) -> RedisConfig:
        return cls(
            url=os.environ.get("UPSTASH_REDIS_REST_URL", ""),
            token=os.environ.get("UPSTASH_REDIS_REST_TOKEN", ""),
            prefix=os.environ.get("COZY_REDIS_PREFIX", "cozy:"),
            default_ttl=int(os.environ.get("COZY_REDIS_TTL", "3600")),
        )


@dataclass
class VectorConfig:
    url: str = ""
    token: str = ""

    @classmethod
    def from_env(cls) -> VectorConfig:
        return cls(
            url=os.environ.get("UPSTASH_VECTOR_REST_URL", ""),
            token=os.environ.get("UPSTASH_VECTOR_REST_TOKEN", ""),
        )


@dataclass
class SearchConfig:
    url: str = ""
    token: str = ""

    @classmethod
    def from_env(cls) -> SearchConfig:
        return cls(
            url=os.environ.get("UPSTASH_SEARCH_REST_URL", ""),
            token=os.environ.get("UPSTASH_SEARCH_REST_TOKEN", ""),
        )


@dataclass
class LibSQLConfig:
    db_path: str = "memory.db"

    @classmethod
    def from_env(cls) -> LibSQLConfig:
        return cls(
            db_path=os.environ.get("COZY_LIBSQL_PATH", "memory.db"),
        )


@dataclass
class CozyConfig:
    redis: RedisConfig = field(default_factory=RedisConfig)
    vector: VectorConfig = field(default_factory=VectorConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    libsql: LibSQLConfig = field(default_factory=LibSQLConfig)

    @classmethod
    def from_env(cls) -> CozyConfig:
        return cls(
            redis=RedisConfig.from_env(),
            vector=VectorConfig.from_env(),
            search=SearchConfig.from_env(),
            libsql=LibSQLConfig.from_env(),
        )
