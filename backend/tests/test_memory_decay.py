#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_memory_decay.py — 遗忘与时效（M7）单元测试

覆盖：
  - last_accessed 字段写入/读回
  - touch_accessed 批量刷新
  - _recency_score 优先用 last_accessed
  - archive_stale_c_layer 仅归档超时 C 层
  - run_archival 走通端到端
  - 注入路径 touch（get_memory_injection 后 last_accessed 被刷新）

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_memory_decay.py -v
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import memory_injector as mi  # noqa: E402
from memory_backend import MemoryEntry  # noqa: E402
from memory_sqlite import SQLiteMemoryBackend  # noqa: E402


@pytest.fixture(autouse=True)
def sqlite_mem(tmp_path, monkeypatch):
    backend = SQLiteMemoryBackend(tmp_path / "mem.db")
    monkeypatch.setattr(mi, "_backend", backend)
    mi.invalidate_cache()
    mi.reset_session_writes()
    yield backend
    mi.invalidate_cache()
    mi.reset_session_writes()


# ── last_accessed 基础 ──────────────────────────────────────────

def test_write_sets_last_accessed_none(sqlite_mem):
    eid = sqlite_mem.write("城市", "深圳", "A", "xi")
    entries = sqlite_mem.list_all("xi")
    entry = next(e for e in entries if e.id == eid)
    assert entry.last_accessed is None


def test_touch_accessed_updates_timestamp(sqlite_mem):
    eid = sqlite_mem.write("城市", "深圳", "A", "xi")
    sqlite_mem.touch_accessed([eid])
    entries = sqlite_mem.list_all("xi")
    entry = next(e for e in entries if e.id == eid)
    assert entry.last_accessed is not None


def test_touch_accessed_empty_list_no_error(sqlite_mem):
    sqlite_mem.touch_accessed([])


# ── _recency_score 优先用 last_accessed ─────────────────────────

def test_recency_score_uses_last_accessed():
    old_ts = "2020-01-01T00:00:00"
    recent_ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    entry = MemoryEntry(
        id="t1", agent_id="xi", category="C",
        key="test", value="val", importance=3,
        created_at=old_ts, updated_at=old_ts,
        last_accessed=recent_ts,
    )
    score = mi._recency_score(entry)
    assert score > 0.9

    entry_no_access = MemoryEntry(
        id="t2", agent_id="xi", category="C",
        key="test2", value="val", importance=3,
        created_at=old_ts, updated_at=old_ts,
        last_accessed=None,
    )
    score_old = mi._recency_score(entry_no_access)
    assert score_old < 0.01
    assert score > score_old


# ── archive_stale_c_layer ───────────────────────────────────────

def test_archive_only_stale_c_layer(sqlite_mem):
    old_ts = "2025-01-01T00:00:00"
    recent_ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    # 超时 C 层（应被归档）
    sqlite_mem.write("旧出差", "去北京", "C", "xi", 3)
    with sqlite_mem._conn() as conn:
        conn.execute(
            "UPDATE memories SET updated_at = ?, last_accessed = NULL WHERE key = '旧出差'",
            [old_ts],
        )

    # 新鲜 C 层（不应被归档）
    sqlite_mem.write("新计划", "下周评审", "C", "xi", 3)

    # 超时 A 层（不应被归档——只归档 C 层）
    sqlite_mem.write("生日", "3月14日", "A", "xi", 5)
    with sqlite_mem._conn() as conn:
        conn.execute(
            "UPDATE memories SET updated_at = ?, last_accessed = NULL WHERE key = '生日'",
            [old_ts],
        )

    archived = sqlite_mem.archive_stale_c_layer(days=180)
    assert len(archived) == 1

    remaining = sqlite_mem.list_all("xi")
    keys = {e.key for e in remaining}
    assert "旧出差" not in keys
    assert "新计划" in keys
    assert "生日" in keys


def test_archive_respects_last_accessed(sqlite_mem):
    old_ts = "2025-01-01T00:00:00"

    sqlite_mem.write("旧但活跃", "某状态", "C", "xi", 3)
    with sqlite_mem._conn() as conn:
        conn.execute(
            "UPDATE memories SET updated_at = ? WHERE key = '旧但活跃'",
            [old_ts],
        )
    # touch 使 last_accessed 为"刚刚"
    entry = next(e for e in sqlite_mem.list_all("xi") if e.key == "旧但活跃")
    sqlite_mem.touch_accessed([entry.id])

    archived = sqlite_mem.archive_stale_c_layer(days=180)
    assert len(archived) == 0


# ── run_archival 端到端 ─────────────────────────────────────────

def test_run_archival_returns_count(sqlite_mem):
    result = mi.run_archival()
    assert result["archived"] == 0


# ── 注入路径 touch ──────────────────────────────────────────────

def test_injection_touches_accessed(sqlite_mem):
    sqlite_mem.write("城市", "深圳", "A", "xi", 5)
    mi.invalidate_cache()
    mi.get_memory_injection("xi", "")
    entries = sqlite_mem.list_all("xi")
    entry = next(e for e in entries if e.key == "城市")
    assert entry.last_accessed is not None
