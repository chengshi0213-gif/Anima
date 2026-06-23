#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_memory_audit.py — 记忆管家（Phase 3）单元测试

覆盖：
  - archive_stale_c_layer 现在是**可回溯归档**（进 memory_history，不再硬删）
  - merge_near_duplicates：同分类纯重复 → 留留存权重最高的一条，其余进时间线(reason='merge')
  - 不同 value / 不同分类不合并（保守，不静默吞信息）
  - run_weekly_memory_audit SOP 入口返回汇总，且无争议项静默处理

运行:
    cd E:\\AI\\workspace\\Anima\\backend
    python -m pytest tests/test_memory_audit.py -v
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import memory_injector as mi  # noqa: E402
from memory_sqlite import SQLiteMemoryBackend  # noqa: E402
from scholar_worker import ShoucangWorker  # noqa: E402

_OLD = "2024-01-01T00:00:00"


@pytest.fixture(autouse=True)
def sqlite_mem(tmp_path, monkeypatch):
    backend = SQLiteMemoryBackend(tmp_path / "mem.db")
    monkeypatch.setattr(mi, "_backend", backend)
    mi.invalidate_cache()
    yield backend
    mi.invalidate_cache()


# ── 可回溯归档 ──────────────────────────────────────────────────

def test_stale_c_layer_archived_recoverably(sqlite_mem):
    eid = sqlite_mem.write("旧状态", "上周在改方案", "C", "xi", 3)
    with sqlite_mem._conn() as conn:
        conn.execute(
            "UPDATE memories SET updated_at = ?, last_accessed = NULL WHERE id = ?",
            [_OLD, eid],
        )

    archived = sqlite_mem.archive_stale_c_layer(days=180)
    assert eid in archived

    # 不再活跃
    assert all(e.id != eid for e in sqlite_mem.list_all("xi"))
    # 但可回溯：进了演化时间线，reason='archive'
    hist = sqlite_mem.history(eid)
    assert any(h["reason"] == "archive" and h["value"] == "上周在改方案" for h in hist)


def test_fresh_c_layer_not_archived(sqlite_mem):
    sqlite_mem.write("新状态", "今天开了会", "C", "xi", 3)
    archived = sqlite_mem.archive_stale_c_layer(days=180)
    assert archived == []


# ── 纯重复合并 ──────────────────────────────────────────────────

def test_merge_pure_duplicates_keeps_highest_retention(sqlite_mem):
    # 同分类、规整后 value 完全一致（标点/空格不同也算重复）；不同 key 才能共存
    keep = sqlite_mem.write("状态A", "我在做跨境电商", "C", "xi", 3, source="desktop:work")
    drop = sqlite_mem.write("状态B", "我在做 跨境电商。", "C", "xi", 3, source="feishu")

    merges = sqlite_mem.merge_near_duplicates()
    assert len(merges) == 1
    m = merges[0]
    # desktop 来源(亲手)留存权重更高 → 被保留
    assert m["kept"] == keep
    assert drop in m["archived"]

    ids = {e.id for e in sqlite_mem.list_all("xi")}
    assert keep in ids and drop not in ids
    # 被合并掉的可回溯
    assert any(h["reason"] == "merge" for h in sqlite_mem.history(drop))


def test_distinct_values_not_merged(sqlite_mem):
    sqlite_mem.write("k1", "喜欢喝美式", "B", "xi", 3)
    sqlite_mem.write("k2", "喜欢喝拿铁", "B", "xi", 3)
    assert sqlite_mem.merge_near_duplicates() == []
    assert len(sqlite_mem.list_all("xi")) == 2


def test_same_value_across_categories_not_merged(sqlite_mem):
    sqlite_mem.write("k1", "完全一样的话", "B", "xi", 3)
    sqlite_mem.write("k2", "完全一样的话", "C", "xi", 3)
    assert sqlite_mem.merge_near_duplicates() == []
    assert len(sqlite_mem.list_all("xi")) == 2


# ── SOP 入口 ────────────────────────────────────────────────────

def test_weekly_audit_sop_runs_silently(sqlite_mem):
    # 一条过时 C + 一对纯重复
    eid = sqlite_mem.write("旧状态", "很久以前的事", "C", "xi", 3)
    with sqlite_mem._conn() as conn:
        conn.execute("UPDATE memories SET updated_at = ?, last_accessed = NULL WHERE id = ?",
                     [_OLD, eid])
    sqlite_mem.write("dupA", "重复内容", "C", "xi", 3, source="desktop")
    sqlite_mem.write("dupB", "重复内容", "C", "xi", 3, source="feishu")

    worker = ShoucangWorker()
    result = worker.run_weekly_memory_audit()

    assert result["status"] == "ok"
    assert eid in result["archived"]
    assert sum(len(m["archived"]) for m in result["merged"]) == 1
    assert "记忆体检完成" in result["summary"]


def test_weekly_audit_sop_noop_when_clean(sqlite_mem):
    sqlite_mem.write("唯一", "今天的新鲜事", "C", "xi", 3)
    worker = ShoucangWorker()
    result = worker.run_weekly_memory_audit()
    assert result["status"] == "ok"
    assert result["archived"] == []
    assert result["merged"] == []
