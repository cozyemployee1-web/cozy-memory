"""libSQL backend — local persistence, adapts to existing schema."""

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
    """Local SQLite-backed persistent memory store.
    Adapts to existing working memory schema if present."""

    def __init__(self, config: LibSQLConfig | None = None):
        self.config = config or LibSQLConfig.from_env()
        self._conn: sqlite3.Connection | None = None
        self._schema: str | None = None  # "existing" or "cozy"

    def _get_conn(self) -> sqlite3.Connection:
        """Lazy connection with auto schema detection."""
        if self._conn is None:
            db_path = Path(self.config.db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path))
            self._conn.row_factory = sqlite3.Row
            self._detect_schema()
        return self._conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_conn()

    @property
    def detected_schema(self) -> str:
        """Returns detected schema, ensuring connection is established."""
        self._get_conn()
        return self._schema or "cozy"

    def _detect_schema(self):
        """Detect if existing working memory schema or our own."""
        tables = {
            row["name"]
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "salience_log" in tables and "query_history" in tables:
            self._schema = "existing"
        else:
            self._schema = "cozy"
            self._ensure_cozy_schema()

    def _ensure_cozy_schema(self):
        self._conn.executescript("""
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
            CREATE INDEX IF NOT EXISTS idx_rel_source ON relations(source_id);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON relations(target_id);

            CREATE TABLE IF NOT EXISTS memory_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_memlog_ts ON memory_log(timestamp DESC);
        """)
        self._conn.commit()

    # ── Entity CRUD (schema-adaptive) ──────────────────────────

    def _row_to_entity(self, row: sqlite3.Row) -> Entity:
        """Convert a DB row to Entity, adapting to schema."""
        if self._schema == "existing":
            props = json.loads(row["properties"]) if row["properties"] else {}
            salience = row["computed_salience"] or row["explicit_salience"] or 1.0
            return Entity(
                id=row["id"],
                type=row["type"],
                name=props.get("name", row["id"]),
                description=props.get("description", ""),
                metadata=props,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                salience=salience,
            )
        else:
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

    def upsert_entity(
        self,
        id: str,
        type: str,
        name: str = "",
        description: str = "",
        metadata: dict | None = None,
        salience: float = 1.0,
        embedding: list[float] | None = None,
    ) -> Entity:
        now = time.time()
        if self._schema == "existing":
            props = {"name": name or id, "description": description, **(metadata or {})}
            props_json = json.dumps(props)
            search_text = f"{name} {description}"
            self.conn.execute("""
                INSERT INTO entities (id, type, created_at, updated_at, last_accessed_at,
                    access_count, explicit_salience, computed_salience, properties, search_text)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type = excluded.type,
                    updated_at = excluded.updated_at,
                    explicit_salience = excluded.explicit_salience,
                    computed_salience = excluded.computed_salience,
                    properties = excluded.properties,
                    search_text = excluded.search_text
            """, (id, type, now, now, now, salience, salience, props_json, search_text))
        else:
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
            """, (id, type, name or id, description, meta_json, now, now, salience, embedding_blob))
        self.conn.commit()
        return self.get_entity(id)

    def get_entity(self, id: str) -> Entity | None:
        row = self.conn.execute("SELECT * FROM entities WHERE id = ?", (id,)).fetchone()
        if not row:
            return None
        return self._row_to_entity(row)

    def list_entities(
        self,
        type: str | None = None,
        limit: int = 50,
        min_salience: float = 0.0,
    ) -> list[Entity]:
        schema = self.detected_schema
        if schema == "existing":
            query = "SELECT * FROM entities WHERE COALESCE(computed_salience, 0) >= ?"
        else:
            query = "SELECT * FROM entities WHERE salience >= ?"
        params: list = [min_salience]
        if type:
            query += " AND type = ?"
            params.append(type)
        if schema == "existing":
            query += " ORDER BY COALESCE(computed_salience, 0) DESC LIMIT ?"
        else:
            query += " ORDER BY salience DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def delete_entity(self, id: str) -> bool:
        cursor = self.conn.execute("DELETE FROM entities WHERE id = ?", (id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def search_entities(self, query: str, limit: int = 20) -> list[Entity]:
        """Search entities. Uses FTS5 if available, falls back to LIKE."""
        schema = self.detected_schema
        if schema == "existing":
            try:
                rows = self.conn.execute("""
                    SELECT e.* FROM entities e
                    JOIN entities_fts fts ON e.rowid = fts.rowid
                    WHERE entities_fts MATCH ?
                    LIMIT ?
                """, (query, limit)).fetchall()
                if rows:
                    return [self._row_to_entity(r) for r in rows]
            except Exception:
                pass
            rows = self.conn.execute("""
                SELECT * FROM entities
                WHERE properties LIKE ? OR id LIKE ? OR type LIKE ?
                ORDER BY COALESCE(computed_salience, 0) DESC LIMIT ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
        else:
            rows = self.conn.execute("""
                SELECT * FROM entities
                WHERE name LIKE ? OR description LIKE ?
                ORDER BY salience DESC LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit)).fetchall()
        return [self._row_to_entity(r) for r in rows]

    # ── Relations ──────────────────────────────────────────────

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        metadata: dict | None = None,
    ) -> int:
        now = time.time()
        if self._schema == "existing":
            cursor = self.conn.execute("""
                INSERT INTO relations (from_id, rel_type, to_id, created_at, weight, properties)
                VALUES (?, ?, ?, ?, 1.0, ?)
            """, (source_id, relation_type, target_id, now, json.dumps(metadata or {})))
        else:
            cursor = self.conn.execute("""
                INSERT INTO relations (source_id, target_id, relation_type, metadata, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (source_id, target_id, relation_type, json.dumps(metadata or {}), now))
        self.conn.commit()
        return cursor.lastrowid

    def get_relations(self, entity_id: str) -> list[dict]:
        if self._schema == "existing":
            rows = self.conn.execute("""
                SELECT * FROM relations WHERE from_id = ? OR to_id = ?
                ORDER BY created_at DESC
            """, (entity_id, entity_id)).fetchall()
        else:
            rows = self.conn.execute("""
                SELECT * FROM relations WHERE source_id = ? OR target_id = ?
                ORDER BY created_at DESC
            """, (entity_id, entity_id)).fetchall()
        return [dict(r) for r in rows]

    # ── Memory Log ─────────────────────────────────────────────

    def log(self, category: str, content: str, metadata: dict | None = None) -> int:
        now = time.time()
        if self._schema == "existing":
            cursor = self.conn.execute("""
                INSERT INTO salience_log (entity_id, event_type, timestamp, delta, context)
                VALUES (?, ?, ?, 0, ?)
            """, ("_system", category, now, json.dumps({"content": content, **(metadata or {})})))
        else:
            cursor = self.conn.execute("""
                INSERT INTO memory_log (timestamp, category, content, metadata)
                VALUES (?, ?, ?, ?)
            """, (now, category, content, json.dumps(metadata or {})))
        self.conn.commit()
        return cursor.lastrowid

    def get_log(self, category: str | None = None, limit: int = 50) -> list[dict]:
        if self._schema == "existing":
            if category:
                rows = self.conn.execute(
                    "SELECT * FROM salience_log WHERE event_type = ? ORDER BY timestamp DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM salience_log ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        else:
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

    # ── Health ──────────────────────────────────────────────────

    def ping(self) -> bool:
        try:
            self.conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def stats(self) -> dict:
        entities = self.conn.execute("SELECT COUNT(*) as c FROM entities").fetchone()["c"]
        relations = self.conn.execute("SELECT COUNT(*) as c FROM relations").fetchone()["c"]
        try:
            if self._schema == "existing":
                log_entries = self.conn.execute("SELECT COUNT(*) as c FROM salience_log").fetchone()["c"]
            else:
                log_entries = self.conn.execute("SELECT COUNT(*) as c FROM memory_log").fetchone()["c"]
        except Exception:
            log_entries = 0
        return {
            "entities": entities,
            "relations": relations,
            "log_entries": log_entries,
            "db_path": self.config.db_path,
            "schema": self._schema or "unknown",
        }
