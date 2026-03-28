"""libSQL backend — local persistence, source of truth for working memory."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import LibSQLConfig


@dataclass
class Entity:
    id: str
    type: str
    name: str
    description: str
    metadata: dict
    created_at: float
    updated_at: float
    salience: float
    embedding: list[float] | None = None


class LibSQLStore:
    """Local SQLite-backed persistent memory store."""

    def __init__(self, config: LibSQLConfig | None = None):
        self.config = config or LibSQLConfig.from_env()
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            db_path = Path(self.config.db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path))
            self._conn.row_factory = sqlite3.Row
            self._ensure_schema()
        return self._conn

    def _ensure_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                salience REAL DEFAULT 1.0,
                embedding BLOB
            );
            CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
            CREATE INDEX IF NOT EXISTS idx_entities_salience ON entities(salience DESC);

            CREATE TABLE IF NOT EXISTS relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                FOREIGN KEY (source_id) REFERENCES entities(id),
                FOREIGN KEY (target_id) REFERENCES entities(id)
            );
            CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
            CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);

            CREATE TABLE IF NOT EXISTS memory_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_memory_log_ts ON memory_log(timestamp DESC);
        """)
        self.conn.commit()

    # ── Entity CRUD ────────────────────────────────────────────

    def upsert_entity(
        self,
        id: str,
        type: str,
        name: str,
        description: str = "",
        metadata: dict | None = None,
        salience: float = 1.0,
        embedding: list[float] | None = None,
    ) -> Entity:
        now = time.time()
        meta_json = json.dumps(metadata or {})
        embedding_blob = None
        if embedding:
            import struct
            embedding_blob = struct.pack(f"{len(embedding)}f", *embedding)

        self.conn.execute("""
            INSERT INTO entities (id, type, name, description, metadata, created_at, updated_at, salience, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type = excluded.type,
                name = excluded.name,
                description = excluded.description,
                metadata = excluded.metadata,
                updated_at = excluded.updated_at,
                salience = excluded.salience,
                embedding = COALESCE(excluded.embedding, entities.embedding)
        """, (id, type, name, description, meta_json, now, now, salience, embedding_blob))
        self.conn.commit()
        return self.get_entity(id)

    def get_entity(self, id: str) -> Entity | None:
        row = self.conn.execute("SELECT * FROM entities WHERE id = ?", (id,)).fetchone()
        if not row:
            return None
        return Entity(
            id=row["id"],
            type=row["type"],
            name=row["name"],
            description=row["description"],
            metadata=json.loads(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            salience=row["salience"],
        )

    def list_entities(
        self,
        type: str | None = None,
        limit: int = 50,
        min_salience: float = 0.0,
    ) -> list[Entity]:
        query = "SELECT * FROM entities WHERE salience >= ?"
        params: list = [min_salience]
        if type:
            query += " AND type = ?"
            params.append(type)
        query += " ORDER BY salience DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [
            Entity(
                id=r["id"], type=r["type"], name=r["name"],
                description=r["description"],
                metadata=json.loads(r["metadata"]),
                created_at=r["created_at"], updated_at=r["updated_at"],
                salience=r["salience"],
            )
            for r in rows
        ]

    def delete_entity(self, id: str) -> bool:
        cursor = self.conn.execute("DELETE FROM entities WHERE id = ?", (id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def search_entities(self, query: str, limit: int = 20) -> list[Entity]:
        """Simple LIKE-based text search on name and description."""
        rows = self.conn.execute("""
            SELECT * FROM entities
            WHERE name LIKE ? OR description LIKE ?
            ORDER BY salience DESC LIMIT ?
        """, (f"%{query}%", f"%{query}%", limit)).fetchall()
        return [
            Entity(
                id=r["id"], type=r["type"], name=r["name"],
                description=r["description"],
                metadata=json.loads(r["metadata"]),
                created_at=r["created_at"], updated_at=r["updated_at"],
                salience=r["salience"],
            )
            for r in rows
        ]

    # ── Relations ──────────────────────────────────────────────

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        metadata: dict | None = None,
    ) -> int:
        cursor = self.conn.execute("""
            INSERT INTO relations (source_id, target_id, relation_type, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (source_id, target_id, relation_type, json.dumps(metadata or {}), time.time()))
        self.conn.commit()
        return cursor.lastrowid

    def get_relations(self, entity_id: str) -> list[dict]:
        rows = self.conn.execute("""
            SELECT * FROM relations
            WHERE source_id = ? OR target_id = ?
            ORDER BY created_at DESC
        """, (entity_id, entity_id)).fetchall()
        return [dict(r) for r in rows]

    # ── Memory Log ─────────────────────────────────────────────

    def log(self, category: str, content: str, metadata: dict | None = None) -> int:
        cursor = self.conn.execute("""
            INSERT INTO memory_log (timestamp, category, content, metadata)
            VALUES (?, ?, ?, ?)
        """, (time.time(), category, content, json.dumps(metadata or {})))
        self.conn.commit()
        return cursor.lastrowid

    def get_log(self, category: str | None = None, limit: int = 50) -> list[dict]:
        if category:
            rows = self.conn.execute(
                "SELECT * FROM memory_log WHERE category = ? ORDER BY timestamp DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM memory_log ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Health ─────────────────────────────────────────────────

    def ping(self) -> bool:
        try:
            self.conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def stats(self) -> dict:
        entities = self.conn.execute("SELECT COUNT(*) as c FROM entities").fetchone()["c"]
        relations = self.conn.execute("SELECT COUNT(*) as c FROM relations").fetchone()["c"]
        log_entries = self.conn.execute("SELECT COUNT(*) as c FROM memory_log").fetchone()["c"]
        return {
            "entities": entities,
            "relations": relations,
            "log_entries": log_entries,
            "db_path": self.config.db_path,
        }
