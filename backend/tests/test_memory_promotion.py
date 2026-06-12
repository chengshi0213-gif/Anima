#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_memory_promotion.py — 每周记忆升格（M2b）单元测试

覆盖：
  - L2 是 xi 的 always-on 画像层分类之一
  - write_l2_insight：写入时附「｜来源：id1,id2」标注，注入文本里隐去
  - 同 key / 近义 key 合并为一条，不堆重复
  - 画像层 L2 条数超过上限（12）时自动淘汰"重要度最低、最久未更新"的
  - scholar_worker._remember(category="L2") 正确路由到 write_l2_insight
  - REMEMBER_DEF 暴露 source_ids 参数 + L2 分类说明
  - run_weekly_promotion：无 L1 事实时直接 skip（不触发 LLM 调用）
  - 每周升格的 cron 触发器可被调度器正确解析
  - M9：cap_divination.record_chart_insight 把命理解读结论写成 L2 画像
    （来源=命理，importance=2，待验证）

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_memory_promotion.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import memory_injector as mi  # noqa: E402
from memory_backend import AGENT_MEMORY_CATEGORIES  # noqa: E402
from memory_sqlite import SQLiteMemoryBackend  # noqa: E402
import scholar_worker as sw  # noqa: E402


@pytest.fixture(autouse=True)
def sqlite_mem(tmp_path, monkeypatch):
    backend = SQLiteMemoryBackend(tmp_path / "mem.db")
    monkeypatch.setattr(mi, "_backend", backend)
    mi.invalidate_cache()
    mi.reset_session_writes()
    yield backend
    mi.invalidate_cache()
    mi.reset_session_writes()


# ── L2 分类接入 ──────────────────────────────────────────────────

def test_xi_profile_categories_include_l2():
    assert "L2" in AGENT_MEMORY_CATEGORIES["xi"]


# ── write_l2_insight：写入 / 来源标注 ────────────────────────────

def test_write_l2_insight_basic_with_source_ids(sqlite_mem):
    r = mi.write_l2_insight(key="作息规律", value="深夜容易陷入低谷期",
                            agent_id="xi", importance=4,
                            source_ids=["fact1", "fact2"])
    assert r["ok"] is True
    assert r["merged"] is False

    entry = next(e for e in mi.list_memory("xi") if e.key == "作息规律")
    assert entry.category == "L2"
    assert entry.value == "深夜容易陷入低谷期｜来源：fact1,fact2"


def test_l2_injection_shows_in_profile_without_source_tag(sqlite_mem):
    mi.write_l2_insight(key="作息规律", value="深夜容易陷入低谷期",
                        agent_id="xi", importance=4,
                        source_ids=["fact1", "fact2"])
    mi.invalidate_cache("xi")

    injection = mi.get_memory_injection("xi")
    assert "作息规律：深夜容易陷入低谷期" in injection
    assert "｜来源：" not in injection
    assert "fact1" not in injection


# ── 合并：同 key / 近义 key ──────────────────────────────────────

def test_write_l2_insight_merges_exact_same_key(sqlite_mem):
    r1 = mi.write_l2_insight(key="作息规律", value="深夜容易陷入低谷期",
                             agent_id="xi", importance=4, source_ids=["fact1"])
    r2 = mi.write_l2_insight(key="作息规律", value="凌晨效率明显下降",
                             agent_id="xi", importance=4,
                             source_ids=["fact1", "fact2"])
    assert r1["id"] == r2["id"]
    assert r2["merged"] is True

    entries = [e for e in mi.list_memory("xi") if e.category == "L2"]
    assert len(entries) == 1
    assert entries[0].value == "凌晨效率明显下降｜来源：fact1,fact2"


def test_write_l2_insight_merges_similar_key(sqlite_mem):
    r1 = mi.write_l2_insight(key="深夜状态低谷", value="凌晨容易状态差",
                             agent_id="xi", importance=4, source_ids=["fact1"])
    r2 = mi.write_l2_insight(key="深夜状态低谷期", value="凌晨容易状态差，且持续多周",
                             agent_id="xi", importance=4,
                             source_ids=["fact1", "fact2"])
    assert r2["merged"] is True
    assert r2["id"] == r1["id"]
    assert r2["key"] == "深夜状态低谷"   # 沿用已有条目的 key

    entries = [e for e in mi.list_memory("xi") if e.category == "L2"]
    assert len(entries) == 1


# ── 淘汰：超过上限保留 12 条 ──────────────────────────────────────

def test_evict_excess_l2_keeps_lowest_importance_out(sqlite_mem):
    # 直接写 13 条互不相似的 L2 条目，绕开合并检测，只测淘汰逻辑
    for i in range(13):
        importance = 1 if i == 0 else 5
        sqlite_mem.write(f"L2洞察{i}号", f"内容{i}", category="L2",
                        agent_id="xi", importance=importance)

    evicted = mi._evict_excess_l2("xi")
    remaining = [e for e in mi.list_memory("xi") if e.category == "L2"]

    assert len(remaining) == 12
    assert "L2洞察0号" in evicted
    assert all(e.key != "L2洞察0号" for e in remaining)


def test_write_l2_insight_triggers_eviction(sqlite_mem):
    for i in range(12):
        sqlite_mem.write(f"既有洞察{i}号", f"内容{i}", category="L2",
                        agent_id="xi", importance=5)

    r = mi.write_l2_insight(key="新洞察", value="新提炼出的模式",
                            agent_id="xi", importance=3, source_ids=["fact9"])
    assert r["ok"] is True
    assert r["evicted"] == ["新洞察"]   # 新条目重要度最低，刚好被自己挤出去

    entries = [e for e in mi.list_memory("xi") if e.category == "L2"]
    assert len(entries) == 12
    assert all(e.key != "新洞察" for e in entries)


# ── scholar_worker._remember(category="L2") 路由 ─────────────────

def test_remember_l2_routes_to_write_l2_insight(sqlite_mem):
    r = sw._remember("沟通直接", "倾向直接表达需求，不绕弯子", category="L2",
                     agent_id="xi", importance=4,
                     source_ids=["fact10", "fact11"])
    assert r["ok"] is True
    assert r["category"] == "L2"

    entry = next(e for e in mi.list_memory("xi") if e.key == "沟通直接")
    assert entry.category == "L2"
    assert entry.value == "倾向直接表达需求，不绕弯子｜来源：fact10,fact11"


def test_remember_def_exposes_l2_and_source_ids():
    params = sw.REMEMBER_DEF["function"]["parameters"]["properties"]
    assert "source_ids" in params
    assert "L2" in params["category"]["description"]


# ── run_weekly_promotion：无 L1 事实时直接 skip ──────────────────

def test_run_weekly_promotion_skips_when_no_l1_facts(sqlite_mem):
    worker = sw.ShoucangWorker()
    result = worker.run_weekly_promotion()
    assert result["status"] == "skipped"


# ── 调度：每周一 04:30 cron 可被正确解析 ─────────────────────────

def test_weekly_promote_cron_is_valid():
    from scheduler import TaskScheduler
    trigger = TaskScheduler._make_trigger("cron", sw.WEEKLY_PROMOTE_CRON)
    assert trigger is not None


# ── M9：命盘→画像桥 record_chart_insight ──────────────────────────

def test_record_chart_insight_registered():
    import cap_divination as cd
    names = [t["function"]["name"] for t in cd.DIVINATION_TOOL_DEFS]
    assert "record_chart_insight" in names
    assert set(cd.divination_dispatch("xi")) == {
        "paipan", "load_mingli_reference", "search_knowledge", "record_chart_insight",
    }


def test_record_chart_insight_writes_l2_with_low_importance(sqlite_mem):
    import cap_divination as cd
    record_insight = cd.divination_dispatch("xi")["record_chart_insight"]

    r = record_insight(trait="决策风格",
                       insight="我猜你做决定前要把方案想透才动手，我们处久了再验证")
    assert r["ok"] is True
    assert r["category"] == "L2"

    entry = next(e for e in mi.list_memory("xi") if e.key == "决策风格")
    assert entry.category == "L2"
    assert entry.importance == 2
    assert entry.value.startswith("我猜你做决定前要把方案想透才动手")


def test_record_chart_insight_requires_trait_and_insight():
    import cap_divination as cd
    record_insight = cd.divination_dispatch("xi")["record_chart_insight"]

    assert "error" in record_insight(trait="", insight="一句话洞察")
    assert "error" in record_insight(trait="决策风格", insight="")
