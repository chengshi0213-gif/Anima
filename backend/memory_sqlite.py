#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_sqlite.py — SQLite 记忆后端

sqlite3 是标准库，FTS5 全文搜索零额外依赖；语义检索（M4）额外用到 numpy
+ memory_embed（onnxruntime 可选，缺失时自动降级回纯 FTS5）。
数据存储在 ~/.anima/data/memory.db 单文件，可随用户配置覆盖。
"""
from __future__ import annotations

import difflib
import sqlite3
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

import memory_embed
import memory_weight
from memory_backend import (
    MemoryBackend, MemoryEntry, AGENT_MEMORY_CATEGORIES,
)

_DEFAULT_DB = Path.home() / ".anima" / "data" / "memory.db"

# M10：偏好规则文本相似度 ≥ 此值视为同一条规则的更新（合并而非新增）
PREF_RULE_MERGE_THRESHOLD = 0.5

# P0：单条记忆的演化历史最多保留段数，防高频翻烧的 key 让 memory_history 无限膨胀
MAX_HISTORY_PER_ENTRY = 20

# 记忆管家（Phase 3）：自动"纯重复合并"只碰规整后内容完全一致的近重复——
# 语义相近但不全等的留给 LLM 待确认（可能是矛盾/细微差别，不该静默合并）。
_DEDUP_STRIP = str.maketrans("", "", " \t\r\n，。！？；：、,.!?;:")

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
    updated_at  TEXT NOT NULL,
    remind_at   TEXT,
    last_accessed TEXT,
    last_reinforced TEXT
);
CREATE INDEX IF NOT EXISTS idx_mem_agent ON memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_mem_cat   ON memories(category);

-- P0 演化时间线：被取代的旧值进这里（不再原地蒸发），保留生效区间与来源。
-- 不挂 FTS/向量触发器——旧值不该被检索召回。
CREATE TABLE IF NOT EXISTS memory_history (
    id          TEXT PRIMARY KEY,
    entry_id    TEXT NOT NULL,        -- → memories.id
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,        -- 旧值
    category    TEXT,
    importance  INTEGER,
    valid_from  TEXT NOT NULL,        -- 旧值何时生效（= 旧行 updated_at）
    valid_to    TEXT NOT NULL,        -- 何时被取代（= now）
    source      TEXT,                 -- 旧值的来源（渠道/房间）
    reason      TEXT                  -- 'update' | 'merge'
);
CREATE INDEX IF NOT EXISTS idx_memhist_entry ON memory_history(entry_id);

-- 语义向量（M4，本地 embedding 可用时写入；缺失不影响主表）
CREATE TABLE IF NOT EXISTS memory_vectors (
    entry_id TEXT PRIMARY KEY,
    vector   BLOB NOT NULL,
    dim      INTEGER NOT NULL
);

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

-- M10：偏好学习管线（E 程序层）── 隐式信号原始记录
CREATE TABLE IF NOT EXISTS pref_signals (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT,
    domain      TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    original    TEXT,
    edited      TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pref_signal_domain ON pref_signals(domain);

-- M10：周级 LLM 从信号里抽出的 E 程序层偏好规则（按领域分桶）
CREATE TABLE IF NOT EXISTS pref_rules (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT,
    domain      TEXT NOT NULL,
    rule        TEXT NOT NULL,
    source_ids  TEXT,
    importance  INTEGER NOT NULL DEFAULT 4,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pref_rule_domain ON pref_rules(domain);

-- Phase3 子阶段：LLM 巡检发现的待用户确认项。
-- 管家只"建议 + 生成待确认项"，绝不自动改 A/D 类记忆（红线）。
CREATE TABLE IF NOT EXISTS memory_reviews (
    id            TEXT PRIMARY KEY,
    entry_id_a    TEXT NOT NULL,    -- 疑似矛盾/过时的记忆 A
    entry_id_b    TEXT NOT NULL,    -- 疑似矛盾/过时的记忆 B
    category      TEXT,
    conflict_type TEXT NOT NULL,    -- 'identity_conflict' | 'possible_contradiction'
    detail        TEXT,             -- LLM 一句话说明矛盾点
    status        TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'dismissed' | 'resolved'
    created_at    TEXT NOT NULL,
    resolved_at   TEXT,
    resolution    TEXT              -- 用户/系统处置说明
);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON memory_reviews(status);
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
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
            if "remind_at" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN remind_at TEXT")
            if "last_accessed" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN last_accessed TEXT")
            if "source" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN source TEXT")
            if "last_reinforced" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN last_reinforced TEXT")
            # Phase3 子阶段：待确认项表（旧库迁移）
            existing_tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "memory_reviews" not in existing_tables:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS memory_reviews (
                        id            TEXT PRIMARY KEY,
                        entry_id_a    TEXT NOT NULL,
                        entry_id_b    TEXT NOT NULL,
                        category      TEXT,
                        conflict_type TEXT NOT NULL,
                        detail        TEXT,
                        status        TEXT NOT NULL DEFAULT 'open',
                        created_at    TEXT NOT NULL,
                        resolved_at   TEXT,
                        resolution    TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_reviews_status ON memory_reviews(status);
                """)

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
            remind_at=row["remind_at"],
            last_accessed=row["last_accessed"] if "last_accessed" in row.keys() else None,
            source=row["source"] if "source" in row.keys() else None,
            last_reinforced=row["last_reinforced"] if "last_reinforced" in row.keys() else None,
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
              importance: int = 3,
              remind_at: Optional[str] = None,
              source: Optional[str] = None) -> str:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._conn() as conn:
            # upsert by key + agent_id
            existing = conn.execute(
                "SELECT * FROM memories WHERE key = ? AND (agent_id IS ? OR agent_id = ?)",
                [key, agent_id, agent_id],
            ).fetchone()
            if existing:
                eid = existing["id"]
                old_src = existing["source"] if "source" in existing.keys() else None
                # P0 演化时间线：值真的变了才把旧值（连同其来源）归档，旧值不再原地蒸发
                if existing["value"] != value:
                    conn.execute(
                        """INSERT INTO memory_history
                           (id, entry_id, key, value, category, importance,
                            valid_from, valid_to, source, reason)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        [str(uuid.uuid4()), eid, existing["key"], existing["value"],
                         existing["category"], existing["importance"],
                         existing["updated_at"], now, old_src, "update"],
                    )
                    # 留存封顶：单条记忆只保留最近 MAX_HISTORY_PER_ENTRY 段历史
                    conn.execute(
                        """DELETE FROM memory_history
                           WHERE entry_id = ? AND id NOT IN (
                               SELECT id FROM memory_history WHERE entry_id = ?
                               ORDER BY valid_to DESC LIMIT ?
                           )""",
                        [eid, eid, MAX_HISTORY_PER_ENTRY],
                    )
                # 来源缺省（None）时保留旧来源，避免无 source 的直写路径抹掉 provenance
                new_src = source if source is not None else old_src
                # 同 key 再次写入 = 现实又印证/重述了一次 → 刷新 last_reinforced
                conn.execute(
                    "UPDATE memories SET value=?, category=?, importance=?, updated_at=?, remind_at=?, source=?, last_reinforced=? WHERE id=?",
                    [value, category, importance, now, remind_at, new_src, now, eid],
                )
            else:
                eid = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO memories
                       (id, agent_id, category, key, value, importance, created_at, updated_at, remind_at, source, last_reinforced)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    [eid, agent_id, category, key, value, importance, now, now, remind_at, source, now],
                )
            self._upsert_vector(conn, eid, key, value)
        return eid

    def _upsert_vector(self, conn: sqlite3.Connection, entry_id: str, key: str, value: str) -> None:
        """写入/刷新一条记忆的语义向量（M4）。embedding 不可用时静默跳过。"""
        try:
            vecs = memory_embed.embed_texts([f"{key}\n{value}"])
            if vecs is None or vecs.shape[0] == 0:
                return
            vec = vecs[0]
            conn.execute(
                "INSERT OR REPLACE INTO memory_vectors (entry_id, vector, dim) VALUES (?,?,?)",
                [entry_id, vec.astype(np.float32).tobytes(), int(vec.shape[0])],
            )
        except Exception:
            pass

    def vector_search(self,
                      query: str,
                      agent_id: Optional[str] = None,
                      limit: int = 10,
                      min_score: Optional[float] = None) -> list[tuple[MemoryEntry, float]]:
        """语义检索（M4）：embedding 不可用或无向量数据时返回空列表，不报错。

        min_score 默认使用 memory_embed.VECTOR_SIM_THRESHOLD；M5 复合分排序
        传 min_score=0.0，以拿到候选条目的全部相关性分数（不做召回过滤）。"""
        threshold = memory_embed.VECTOR_SIM_THRESHOLD if min_score is None else min_score
        q_vecs = memory_embed.embed_texts([query])
        if q_vecs is None or q_vecs.shape[0] == 0:
            return []
        q_vec = q_vecs[0]

        with self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    """SELECT m.*, v.vector, v.dim FROM memories m
                       JOIN memory_vectors v ON v.entry_id = m.id
                       WHERE m.agent_id IS NULL OR m.agent_id = ?""",
                    [agent_id],
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT m.*, v.vector, v.dim FROM memories m
                       JOIN memory_vectors v ON v.entry_id = m.id"""
                ).fetchall()

        rows = [r for r in rows if r["dim"] == q_vec.shape[0]]
        if not rows:
            return []

        matrix = np.stack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
        scores = memory_embed.cosine_sim(q_vec, matrix)
        ranked = sorted(range(len(rows)), key=lambda i: scores[i], reverse=True)
        return [
            (self._row(rows[i]), float(scores[i]))
            for i in ranked
            if scores[i] >= threshold
        ][:limit]

    def _fts_search(self,
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

    def search(self,
               query: str,
               agent_id: Optional[str] = None,
               limit: int = 10) -> list[MemoryEntry]:
        """FTS5 ∪ 余弦相似度合并去重（M4）：关键词命中优先，语义召回补充。"""
        results = self._fts_search(query, agent_id, limit)
        seen = {e.id for e in results}
        for entry, _score in self.vector_search(query, agent_id, limit):
            if entry.id in seen:
                continue
            results.append(entry)
            seen.add(entry.id)
            if len(results) >= limit:
                break
        return results[:limit]

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

    def history(self, entry_id: str) -> list[dict]:
        """P0 演化时间线：返回某条记忆被取代过的旧值，按 valid_to 倒序（最近一次变更在前）。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_history WHERE entry_id = ? ORDER BY valid_to DESC",
                [entry_id],
            ).fetchall()
        return [dict(r) for r in rows]

    def due_reminders(self,
                      agent_id: Optional[str] = None,
                      within_days: int = 1) -> list[MemoryEntry]:
        """M8 式④：到期/临近到期（remind_at <= 今天 + within_days）的记忆，按 remind_at 升序。"""
        cutoff = (date.today() + timedelta(days=within_days)).isoformat()
        with self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    """SELECT * FROM memories
                       WHERE remind_at IS NOT NULL AND remind_at != ''
                         AND remind_at <= ?
                         AND (agent_id IS NULL OR agent_id = ?)
                       ORDER BY remind_at ASC""",
                    [cutoff, agent_id],
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM memories
                       WHERE remind_at IS NOT NULL AND remind_at != ''
                         AND remind_at <= ?
                       ORDER BY remind_at ASC""",
                    [cutoff],
                ).fetchall()
        return [self._row(r) for r in rows]

    def delete(self, entry_id: str) -> bool:
        with self._conn() as conn:
            n = conn.execute("DELETE FROM memories WHERE id = ?", [entry_id]).rowcount
            conn.execute("DELETE FROM memory_vectors WHERE entry_id = ?", [entry_id])
        return n > 0

    # ── 迁移接口 ─────────────────────────────────────────────────

    def export_snapshot(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY created_at"
            ).fetchall()
            try:
                hist = conn.execute(
                    "SELECT * FROM memory_history ORDER BY valid_to"
                ).fetchall()
            except Exception:
                hist = []
        return {
            "backend":     "sqlite",
            "version":     1,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "db_path":     str(self._db_path),
            "memories":    [dict(r) for r in rows],
            "history":     [dict(r) for r in hist],
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
                            (id, agent_id, category, key, value, importance, created_at, updated_at, remind_at, source)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        [eid,
                         m.get("agent_id"),
                         m.get("category", "general"),
                         m.get("key", ""),
                         m.get("value", ""),
                         int(m.get("importance", 3)),
                         m.get("created_at", now),
                         m.get("updated_at", now),
                         m.get("remind_at"),
                         m.get("source")],
                    )
                count += 1
            except Exception:
                pass
        # P0 演化时间线随快照一并迁移（旧快照无 history 字段则自然跳过）
        for h in data.get("history", []):
            try:
                with self._conn() as conn:
                    conn.execute(
                        """INSERT OR IGNORE INTO memory_history
                           (id, entry_id, key, value, category, importance,
                            valid_from, valid_to, source, reason)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        [h.get("id") or str(uuid.uuid4()),
                         h.get("entry_id", ""),
                         h.get("key", ""),
                         h.get("value", ""),
                         h.get("category"),
                         h.get("importance"),
                         h.get("valid_from", now),
                         h.get("valid_to", now),
                         h.get("source"),
                         h.get("reason", "update")],
                    )
            except Exception:
                pass
        return count

    # ── M10：偏好学习管线（E 程序层）──────────────────────────────

    def record_pref_signal(self,
                           domain: str,
                           signal_type: str,
                           original: Optional[str] = None,
                           edited: Optional[str] = None,
                           note: Optional[str] = None,
                           agent_id: Optional[str] = None) -> str:
        """记一条隐式信号（编辑 diff / 吐槽 / 采纳）原始记录。"""
        sid = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO pref_signals
                   (id, agent_id, domain, signal_type, original, edited, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [sid, agent_id, domain, signal_type, original, edited, note, now],
            )
        return sid

    def list_pref_signals(self,
                          domain: Optional[str] = None,
                          limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            if domain:
                rows = conn.execute(
                    """SELECT * FROM pref_signals WHERE domain = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    [domain, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM pref_signals ORDER BY created_at DESC LIMIT ?",
                    [limit],
                ).fetchall()
        return [dict(r) for r in rows]

    def count_pref_signals_by_domain(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT domain, COUNT(*) AS n FROM pref_signals GROUP BY domain"
            ).fetchall()
        return {r["domain"]: r["n"] for r in rows}

    def _find_existing_pref_rule(self, domain: str, rule: str) -> Optional[sqlite3.Row]:
        """同领域下找文本相似度 ≥ PREF_RULE_MERGE_THRESHOLD 的已有规则，用于合并而非新增。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pref_rules WHERE domain = ?", [domain],
            ).fetchall()
        best, best_score = None, 0.0
        for r in rows:
            score = difflib.SequenceMatcher(
                None, r["rule"].strip().lower(), rule.strip().lower()
            ).ratio()
            if score > best_score:
                best, best_score = r, score
        return best if best_score >= PREF_RULE_MERGE_THRESHOLD else None

    def write_pref_rule(self,
                        domain: str,
                        rule: str,
                        source_ids: Optional[list[str]] = None,
                        agent_id: Optional[str] = None,
                        importance: int = 4,
                        max_per_domain: int = 8) -> dict:
        """写入/更新一条 E 程序层偏好规则（周级 LLM 抽取专用）。

        - 同领域下文本近似的已有规则会被更新（合并），不会重复新增。
        - 写入后若该领域规则数超过 max_per_domain，自动淘汰
          "重要度最低、最久未更新"的规则，防单域膨胀。
        """
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        src = ",".join(source_ids) if source_ids else None
        existing = self._find_existing_pref_rule(domain, rule)
        merged = existing is not None
        with self._conn() as conn:
            if existing:
                rid = existing["id"]
                conn.execute(
                    """UPDATE pref_rules SET rule=?, source_ids=?, importance=?, updated_at=?
                       WHERE id=?""",
                    [rule, src, importance, now, rid],
                )
            else:
                rid = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO pref_rules
                       (id, agent_id, domain, rule, source_ids, importance, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    [rid, agent_id, domain, rule, src, importance, now, now],
                )
        evicted = self._evict_excess_pref_rules(domain, max_per_domain)
        return {"ok": True, "id": rid, "domain": domain, "merged": merged, "evicted": evicted}

    def _evict_excess_pref_rules(self, domain: str, max_per_domain: int = 8) -> list[str]:
        """单领域规则数超过 max_per_domain 时，淘汰"重要度最低、最久未更新"的规则。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pref_rules WHERE domain = ?", [domain],
            ).fetchall()
        if len(rows) <= max_per_domain:
            return []
        rows = sorted(rows, key=lambda r: (r["importance"], r["updated_at"]))
        to_evict = rows[: len(rows) - max_per_domain]
        with self._conn() as conn:
            for r in to_evict:
                conn.execute("DELETE FROM pref_rules WHERE id = ?", [r["id"]])
        return [r["id"] for r in to_evict]

    def list_pref_rules(self, domain: Optional[str] = None) -> list[dict]:
        with self._conn() as conn:
            if domain:
                rows = conn.execute(
                    """SELECT * FROM pref_rules WHERE domain = ?
                       ORDER BY importance DESC, updated_at DESC""",
                    [domain],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM pref_rules ORDER BY domain, importance DESC, updated_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    # ── M7：遗忘与时效 ────────────────────────────────────────────

    def touch_accessed(self, entry_ids: list[str]) -> None:
        """批量刷新 last_accessed（注入/检索命中时调用）。"""
        if not entry_ids:
            return
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._conn() as conn:
            for eid in entry_ids:
                conn.execute(
                    "UPDATE memories SET last_accessed = ? WHERE id = ?",
                    [now, eid],
                )

    def _archive_to_history(self, conn: sqlite3.Connection,
                            ids: list[str], reason: str) -> list[str]:
        """把活跃记忆移进演化时间线（memory_history）再从主表删除——可回溯，不真删。

        红线"从不真删，只归档"的落点：被归档/合并掉的条目，旧值连同来源进 history，
        日后能查、能翻回。返回真正归档掉的 ID 列表。
        """
        if not ids:
            return []
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        ph = ",".join("?" * len(ids))
        rows = conn.execute(f"SELECT * FROM memories WHERE id IN ({ph})", ids).fetchall()
        for r in rows:
            src = r["source"] if "source" in r.keys() else None
            conn.execute(
                """INSERT INTO memory_history
                   (id, entry_id, key, value, category, importance,
                    valid_from, valid_to, source, reason)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [str(uuid.uuid4()), r["id"], r["key"], r["value"], r["category"],
                 r["importance"], r["updated_at"], now, src, reason],
            )
        archived = [r["id"] for r in rows]
        if archived:
            aph = ",".join("?" * len(archived))
            conn.execute(f"DELETE FROM memories WHERE id IN ({aph})", archived)
            conn.execute(f"DELETE FROM memory_vectors WHERE entry_id IN ({aph})", archived)
        return archived

    def archive_stale_c_layer(self, days: int = 180) -> list[str]:
        """归档超过 days 天未访问且未更新的 C 状态层记忆。
        判断依据：coalesce(last_accessed, updated_at) < cutoff。
        归档 = 移进演化时间线（可回溯），不再硬删。返回被归档的条目 ID 列表。"""
        cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.localtime(time.time() - days * 86400),
        )
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id FROM memories
                   WHERE category = 'C'
                     AND COALESCE(last_accessed, updated_at) < ?""",
                [cutoff],
            ).fetchall()
            ids = [r["id"] for r in rows]
            return self._archive_to_history(conn, ids, reason="archive")

    def merge_near_duplicates(self, now: Optional[float] = None) -> list[dict]:
        """记忆管家（Phase 3）自动"纯重复合并"：同分类下、规整后内容**完全一致**的近重复，
        每簇只留留存权重最高的一条，其余移进演化时间线（reason='merge'，可回溯）。

        只碰真·重复（去掉空白与标点后全等）；语义相近但不全等的不动——那可能是矛盾或
        细微差别，留给 LLM 待确认，绝不静默合并。返回 [{kept, kept_key, archived:[id...]}]。
        """
        rows = self.list_all(limit=10000)
        # (category, 规整value) → 同簇条目
        buckets: dict[tuple, list[MemoryEntry]] = {}
        for e in rows:
            norm = (e.value or "").strip().lower().translate(_DEDUP_STRIP)
            if not norm:
                continue
            buckets.setdefault((e.category, norm), []).append(e)

        merges: list[dict] = []
        archive_ids: list[str] = []
        for (_cat, _norm), items in buckets.items():
            if len(items) < 2:
                continue
            items.sort(key=lambda e: -memory_weight.retention_weight_entry(e, now=now))
            kept, losers = items[0], items[1:]
            archive_ids.extend(le.id for le in losers)
            merges.append({"kept": kept.id, "kept_key": kept.key,
                           "archived": [le.id for le in losers]})

        if archive_ids:
            with self._conn() as conn:
                self._archive_to_history(conn, archive_ids, reason="merge")
        return merges

    # ── 待确认项队列（Phase3 子阶段）─────────────────────────────────

    def add_review(self, entry_id_a: str, entry_id_b: str,
                   category: str, conflict_type: str, detail: str) -> Optional[str]:
        """写入一条待确认项（矛盾/可能过时）。
        若相同两条记忆已有 open 项则去重跳过，返回 None；否则返回新 review id。
        conflict_type: 'identity_conflict'（A/D 类，须用户点头）|
                       'possible_contradiction'（其它类，她找机会问）。
        红线：这里只存建议，绝不改原始记忆，更不删。"""
        pair_a, pair_b = min(entry_id_a, entry_id_b), max(entry_id_a, entry_id_b)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._conn() as conn:
            dup = conn.execute(
                """SELECT id FROM memory_reviews
                   WHERE ((entry_id_a=? AND entry_id_b=?) OR (entry_id_a=? AND entry_id_b=?))
                     AND status='open'""",
                [pair_a, pair_b, pair_b, pair_a],
            ).fetchone()
            if dup:
                return None
            rid = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO memory_reviews
                   (id, entry_id_a, entry_id_b, category, conflict_type, detail, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [rid, pair_a, pair_b, category, conflict_type, detail, "open", now],
            )
        return rid

    def list_pending_reviews(self) -> list[dict]:
        """返回所有 open 待确认项，按 created_at 升序（最老的最先显示）。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_reviews WHERE status='open' ORDER BY created_at ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def resolve_review(self, review_id: str, resolution: str = "",
                       status: str = "resolved") -> bool:
        """把待确认项标为 resolved（用户处置了）或 dismissed（不需要处理）。"""
        if status not in ("resolved", "dismissed"):
            status = "resolved"
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._conn() as conn:
            n = conn.execute(
                """UPDATE memory_reviews
                   SET status=?, resolved_at=?, resolution=?
                   WHERE id=? AND status='open'""",
                [status, now, resolution or "", review_id],
            ).rowcount
        return n > 0

    def find_review_candidates(self,
                               sim_threshold: float = 0.35,
                               max_pairs: int = 30) -> list[dict]:
        """确定性候选发现（不调模型）：同分类内 value 字符 bigram Jaccard 相似度
        超过阈值、但不是纯重复（已被 merge_near_duplicates 处理）的记忆对。

        A/D 类标 identity_conflict；其它类标 possible_contradiction。
        已有 open 待确认项的对去重跳过。返回候选列表供 LLM 进一步裁决。"""
        entries = self.list_all(limit=500)
        buckets: dict[str, list[MemoryEntry]] = {}
        for e in entries:
            buckets.setdefault(e.category or "general", []).append(e)

        with self._conn() as conn:
            open_pairs = {
                (min(r["entry_id_a"], r["entry_id_b"]),
                 max(r["entry_id_a"], r["entry_id_b"]))
                for r in conn.execute(
                    "SELECT entry_id_a, entry_id_b FROM memory_reviews WHERE status='open'"
                ).fetchall()
            }

        def _bigram_jaccard(s1: str, s2: str) -> float:
            if len(s1) < 2 or len(s2) < 2:
                return 0.0
            b1 = {s1[i:i+2] for i in range(len(s1)-1)}
            b2 = {s2[i:i+2] for i in range(len(s2)-1)}
            return len(b1 & b2) / len(b1 | b2)

        candidates: list[dict] = []
        for cat, items in buckets.items():
            if len(items) < 2:
                continue
            conflict_type = (
                "identity_conflict" if cat in ("A", "D")
                else "possible_contradiction"
            )
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    a, b = items[i], items[j]
                    na = (a.value or "").strip().lower().translate(_DEDUP_STRIP)
                    nb = (b.value or "").strip().lower().translate(_DEDUP_STRIP)
                    if na == nb:
                        continue  # 纯重复交给 merge_near_duplicates
                    pair_key = (min(a.id, b.id), max(a.id, b.id))
                    if pair_key in open_pairs:
                        continue
                    sim = _bigram_jaccard(
                        (a.value or "").lower(),
                        (b.value or "").lower(),
                    )
                    if sim >= sim_threshold:
                        candidates.append({
                            "entry_id_a": a.id, "key_a": a.key, "value_a": a.value,
                            "entry_id_b": b.id, "key_b": b.key, "value_b": b.value,
                            "category": cat, "conflict_type": conflict_type,
                            "similarity": round(sim, 3),
                        })
                    if len(candidates) >= max_pairs:
                        break
                if len(candidates) >= max_pairs:
                    break

        candidates.sort(key=lambda x: -x["similarity"])
        return candidates

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
