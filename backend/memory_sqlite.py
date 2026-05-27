#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_sqlite.py — SQLite 记忆后端

零额外依赖（sqlite3 是标准库），FTS5 全文搜索。
数据存储在 ~/.anima/data/memory.db 单文件，可随用户配置覆盖。
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from memory_backend import (
    MemoryBackend, MemoryEntry, AGENT_MEMORY_CATEGORIES,
)

_DEFAULT_DB = Path.home() / ".anima" / "data" / "memory.db"

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT,
    category    TEXT NOT NULL DEFAULT 'general',
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    importance  INTEGER NOT NULL DEFAULT 3,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mem_agent ON memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_mem_cat   ON memories(category);

-- FTS5 全文搜索（中英文均可）
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    key, value, category,
    content=memories,
    content_rowid=rowid,
    tokenize='unicode61 remove_diacritics 2'
);

-- 自动同步触发器
CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, key, value, category)
    VALUES (new.rowid, new.key, new.value, new.category);
END;
CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, key, value, category)
    VALUES ('delete', old.rowid, old.key, old.value, old.category);
END;
CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, key, value, category)
    VALUES ('delete', old.rowid, old.key, old.value, old.category);
    INSERT INTO memories_fts(rowid, key, value, category)
    VALUES (new.rowid, new.key, new.value, new.category);
END;
"""


class SQLiteMemoryBackend(MemoryBackend):
    """
    本地 SQLite 记忆后端。
    - 全文搜索：FTS5（无需额外安装）
    - 迁移：export_snapshot / import_snapshot
    - 同 key 写入自动 upsert
    """

    def __init__(self, db_path: Path = _DEFAULT_DB):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── 内部工具 ─────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @staticmethod
    def _row(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"],
            agent_id=row["agent_id"],
            category=row["category"],
            key=row["key"],
            value=row["value"],
            importance=row["importance"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ── 核心操作 ─────────────────────────────────────────────────

    def read_for_agent(self, agent_id: str, max_chars: int = 1500) -> str:
        cats = AGENT_MEMORY_CATEGORIES.get(agent_id, ["user_profile", "general"])
        ph = ",".join("?" * len(cats))
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM memories
                    WHERE (agent_id IS NULL OR agent_id = ?)
                      AND category IN ({ph})
                    ORDER BY importance DESC, updated_at DESC
                    LIMIT 60""",
                [agent_id] + cats,
            ).fetchall()
        return self._format_injection(agent_id, [self._row(r) for r in rows], max_chars)

    def write(self,
              key: str,
              value: str,
              category: str = "general",
              agent_id: Optional[str] = None,
              importance: int = 3) -> str:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._conn() as conn:
            # upsert by key + agent_id
            existing = conn.execute(
                "SELECT id FROM memories WHERE key = ? AND (agent_id IS ? OR agent_id = ?)",
                [key, agent_id, agent_id],
            ).fetchone()
            if existing:
                eid = existing["id"]
                conn.execute(
                    "UPDATE memories SET value=?, category=?, importance=?, updated_at=? WHERE id=?",
                    [value, category, importance, now, eid],
                )
            else:
                eid = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO memories
                       (id, agent_id, category, key, value, importance, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    [eid, agent_id, category, key, value, importance, now, now],
                )
        return eid

    def search(self,
               query: str,
               agent_id: Optional[str] = None,
               limit: int = 10) -> list[MemoryEntry]:
        # FTS5 match；特殊字符需转义
        safe_q = query.replace('"', '""')
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT m.* FROM memories m
                       JOIN memories_fts fts ON m.rowid = fts.rowid
                       WHERE memories_fts MATCH ?
                         AND (m.agent_id IS NULL OR m.agent_id = ?)
                       ORDER BY rank LIMIT ?""",
                    [safe_q, agent_id, limit],
                ).fetchall()
        except sqlite3.OperationalError:
            # FTS 语法错误时降级为 LIKE
            rows = []
        if not rows:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM memories
                       WHERE (key LIKE ? OR value LIKE ?)
                         AND (agent_id IS NULL OR agent_id = ?)
                       ORDER BY importance DESC LIMIT ?""",
                    [f"%{query}%", f"%{query}%", agent_id, limit],
                ).fetchall()
        return [self._row(r) for r in rows]

    def list_all(self,
                 agent_id: Optional[str] = None,
                 limit: int = 200) -> list[MemoryEntry]:
        with self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    """SELECT * FROM memories
                       WHERE agent_id IS NULL OR agent_id = ?
                       ORDER BY importance DESC, updated_at DESC LIMIT ?""",
                    [agent_id, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memories ORDER BY importance DESC, updated_at DESC LIMIT ?",
                    [limit],
                ).fetchall()
        return [self._row(r) for r in rows]

    def delete(self, entry_id: str) -> bool:
        with self._conn() as conn:
            n = conn.execute("DELETE FROM memories WHERE id = ?", [entry_id]).rowcount
        return n > 0

    # ── 迁移接口 ─────────────────────────────────────────────────

    def export_snapshot(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY created_at"
            ).fetchall()
        return {
            "backend":     "sqlite",
            "version":     1,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "db_path":     str(self._db_path),
            "memories":    [dict(r) for r in rows],
        }

    def import_snapshot(self, data: dict, merge: bool = True) -> int:
        count = 0
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        policy = "INSERT OR IGNORE" if merge else "INSERT OR REPLACE"
        for m in data.get("memories", []):
            try:
                eid = m.get("id") or str(uuid.uuid4())
                with self._conn() as conn:
                    conn.execute(
                        f"""{policy} INTO memories
                            (id, agent_id, category, key, value, importance, created_at, updated_at)
                            VALUES (?,?,?,?,?,?,?,?)""",
                        [eid,
                         m.get("agent_id"),
                         m.get("category", "general"),
                         m.get("key", ""),
                         m.get("value", ""),
                         int(m.get("importance", 3)),
                         m.get("created_at", now),
                         m.get("updated_at", now)],
                    )
                count += 1
            except Exception:
                pass
        return count

    # ── 元信息 ───────────────────────────────────────────────────

    def get_backend_type(self) -> str:
        return "sqlite"

    def get_status(self) -> dict:
        try:
            with self._conn() as conn:
                total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        except Exception:
            total = 0
        return {
            "type":      "sqlite",
            "label":     "本地存储",
            "ok":        True,
            "db_path":   str(self._db_path),
            "entries":   total,
            "size_kb":   round(self._db_path.stat().st_size / 1024, 1) if self._db_path.exists() else 0,
        }
