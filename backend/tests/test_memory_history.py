#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_memory_history.py — P0 演化时间线 + 来源(provenance) 单元测试

验证记忆从"覆盖式蒸发"升级为"旧值留痕"：
  - 同 key 改值：旧值（连同来源）归档进 memory_history，不再原地覆盖丢失
  - 同 key 写入相同值：不产生历史噪声
  - get_memory_timeline：返回当前值 + 历次旧值（含来源、生效区间）
  - source 透传：写入来源落库；无 source 的更新保留旧来源（不抹 provenance）
  - 导出/导入：演化时间线随快照一并迁移
  - M3 冲突闸门拦下的写入不进 backend，因此不产生历史

运行:
    python -m pytest tests/test_memory_history.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import memory_injector as mi  # noqa: E402
from memory_sqlite import SQLiteMemoryBackend  # noqa: E402


@pytest.fixture(autouse=True)
def sqlite_mem(tmp_path, monkeypatch):
    """把激活后端换成 tmp 下的独立 SQLite，清注入缓存 + M3 单会话写入计数。"""
    backend = SQLiteMemoryBackend(tmp_path / "mem.db")
    monkeypatch.setattr(mi, "_backend", backend)
    mi.invalidate_cache()
    mi.reset_session_writes()
    yield backend
    mi.invalidate_cache()
    mi.reset_session_writes()


def test_changed_value_archives_old(sqlite_mem):
    backend = sqlite_mem
    eid1 = backend.write("常驻城市", "北京", category="A", agent_id="xi")
    eid2 = backend.write("常驻城市", "上海", category="A", agent_id="xi")
    assert eid1 == eid2  # 同 key upsert，仍是同一条目

    hist = backend.history(eid1)
    assert len(hist) == 1
    assert hist[0]["value"] == "北京"      # 旧值没丢
    assert hist[0]["reason"] == "update"
    assert hist[0]["valid_from"] and hist[0]["valid_to"]

    # 当前值已是上海
    cur = next(e for e in backend.list_all("xi") if e.key == "常驻城市")
    assert cur.value == "上海"


def test_same_value_no_history(sqlite_mem):
    backend = sqlite_mem
    eid = backend.write("口头禅", "好嘞", category="B", agent_id="xi")
    backend.write("口头禅", "好嘞", category="B", agent_id="xi")  # 写入相同值
    assert backend.history(eid) == []


def test_timeline_returns_current_plus_history(sqlite_mem):
    backend = sqlite_mem
    backend.write("常驻城市", "北京", category="A", agent_id="xi")
    backend.write("常驻城市", "上海", category="A", agent_id="xi")

    tl = mi.get_memory_timeline("常驻城市", agent_id="xi")
    assert tl["found"] is True
    assert tl["current"]["value"] == "上海"
    assert [h["value"] for h in tl["history"]] == ["北京"]


def test_timeline_missing_key(sqlite_mem):
    tl = mi.get_memory_timeline("不存在的key", agent_id="xi")
    assert tl["found"] is False


def test_source_persisted_and_archived(sqlite_mem):
    backend = sqlite_mem
    backend.write("常驻城市", "北京", category="A", agent_id="xi", source="feishu")
    backend.write("常驻城市", "上海", category="A", agent_id="xi", source="desktop:work")

    cur = next(e for e in backend.list_all("xi") if e.key == "常驻城市")
    assert cur.source == "desktop:work"            # 当前值带新来源

    hist = backend.history(cur.id)
    assert hist[0]["source"] == "feishu"           # 旧值的来源也被归档


def test_source_preserved_on_sourceless_update(sqlite_mem):
    backend = sqlite_mem
    backend.write("常驻城市", "北京", category="A", agent_id="xi", source="feishu")
    backend.write("常驻城市", "上海", category="A", agent_id="xi")  # 不带 source

    cur = next(e for e in backend.list_all("xi") if e.key == "常驻城市")
    assert cur.source == "feishu"                  # 无 source 的更新不抹掉旧 provenance


def test_export_import_roundtrip_preserves_history(sqlite_mem, tmp_path):
    backend = sqlite_mem
    backend.write("常驻城市", "北京", category="A", agent_id="xi", source="feishu")
    backend.write("常驻城市", "上海", category="A", agent_id="xi", source="desktop")

    snap = backend.export_snapshot()
    assert "history" in snap and len(snap["history"]) >= 1

    fresh = SQLiteMemoryBackend(tmp_path / "mem2.db")
    fresh.import_snapshot(snap, merge=False)
    e = next(x for x in fresh.list_all() if x.key == "常驻城市")
    assert e.value == "上海"
    restored = fresh.history(e.id)
    assert any(h["value"] == "北京" for h in restored)


def test_conflict_refused_leaves_no_history(sqlite_mem):
    """M3 冲突闸门在 backend.write 之前就 return，旧值不覆盖、也不产生历史。"""
    backend = sqlite_mem
    r1 = mi.write_memory_gated("下周行程", "周三去上海出差",
                               category="C", agent_id="xi", importance=3)
    assert r1["ok"] is True
    r2 = mi.write_memory_gated("下周行程", "周三在家加班",
                               category="C", agent_id="xi", importance=3)
    assert r2["ok"] is False and r2["reason"] == "conflict"

    e = next(x for x in mi.list_memory("xi") if x.key == "下周行程")
    assert e.value == "周三去上海出差"     # 旧值原样保留
    assert backend.history(e.id) == []     # 没有历史噪声


# ── Slice B：渠道 provenance（contextvar 透传）─────────────────────

def test_gated_write_tags_source_from_contextvar(sqlite_mem):
    backend = sqlite_mem
    token = mi.CURRENT_SOURCE.set("feishu")
    try:
        r = mi.write_memory_gated("常驻城市", "上海", category="A",
                                  agent_id="xi", importance=4)
        assert r["ok"] is True
    finally:
        mi.CURRENT_SOURCE.reset(token)
    e = next(x for x in backend.list_all("xi") if x.key == "常驻城市")
    assert e.source == "feishu"


def test_explicit_source_overrides_contextvar(sqlite_mem):
    backend = sqlite_mem
    token = mi.CURRENT_SOURCE.set("feishu")
    try:
        mi.write_memory_gated("常驻城市", "广州", category="A",
                              agent_id="xi", importance=4, source="qq")
    finally:
        mi.CURRENT_SOURCE.reset(token)
    e = next(x for x in backend.list_all("xi") if x.key == "常驻城市")
    assert e.source == "qq"     # 显式 source 优先于上下文


def test_default_source_is_desktop(sqlite_mem):
    backend = sqlite_mem
    mi.write_memory_gated("口味", "微辣", category="B", agent_id="xi", importance=3)
    e = next(x for x in backend.list_all("xi") if x.key == "口味")
    assert e.source == "desktop"   # 未设上下文时回落桌面端


# ── 留存封顶 ────────────────────────────────────────────────────

def test_history_capped(sqlite_mem, monkeypatch):
    import memory_sqlite as ms
    monkeypatch.setattr(ms, "MAX_HISTORY_PER_ENTRY", 3)
    backend = sqlite_mem
    eid = backend.write("心情", "v0", category="C", agent_id="xi")
    for i in range(1, 7):          # 连改 6 次 → 本应产生 6 段历史
        backend.write("心情", f"v{i}", category="C", agent_id="xi")
    hist = backend.history(eid)
    assert len(hist) == 3          # 封顶生效，只留 3 段（防无限膨胀）
    # 所有保留段都来自真实写过的旧值（同秒写入下"留哪几段"由 valid_to 决定，不强断顺序）
    assert all(h["value"] in {f"v{i}" for i in range(6)} for h in hist)
