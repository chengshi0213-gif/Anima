#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_memory_quality_gate.py — 写入质量闸门（M3）单元测试

验证 memory_injector.write_memory_gated 的三条拦截路径：
  - 近义 key 合并：同 category 下相似 key 走 upsert，合并进同一条目
  - 冲突检测：同 key 新旧值矛盾时不静默覆盖，返回冲突信息
  - 单会话写入条数上限：超过 MAX_WRITES_PER_SESSION 后续写入被拦截
  - importance 过滤：低重要度且非 A/D 层不写，A/D 层不受影响

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_memory_quality_gate.py -v
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
    """把激活后端换成 tmp 下的独立 SQLite，清注入缓存+M3单会话写入计数。"""
    backend = SQLiteMemoryBackend(tmp_path / "mem.db")
    monkeypatch.setattr(mi, "_backend", backend)
    mi.invalidate_cache()
    mi.reset_session_writes()
    yield backend
    mi.invalidate_cache()
    mi.reset_session_writes()


def test_low_importance_non_ad_not_written():
    r = mi.write_memory_gated("随手记的小事", "今天天气不错",
                              category="general", agent_id="xi", importance=1)
    assert r["ok"] is False
    assert r["reason"] == "low_importance"
    assert mi.list_memory("xi") == []


def test_low_importance_ad_layer_still_written():
    r = mi.write_memory_gated("生日", "3月14日",
                              category="A", agent_id="xi", importance=1)
    assert r["ok"] is True


def test_near_key_merge_upserts_into_existing_entry():
    r1 = mi.write_memory_gated("下周出差安排", "周三去上海，周五回",
                               category="C", agent_id="xi", importance=3)
    assert r1["ok"] is True
    assert r1["merged"] is False

    r2 = mi.write_memory_gated("本周出差安排", "周三去上海，周五回，顺便见客户",
                               category="C", agent_id="xi", importance=3)
    assert r2["ok"] is True
    assert r2["merged"] is True
    assert r2["key"] == r1["key"]   # 合并进同一条目，而不是新建

    entries = [e for e in mi.list_memory("xi") if e.category == "C"]
    assert len(entries) == 1
    assert "顺便见客户" in entries[0].value


def test_conflict_returns_info_without_overwrite():
    r1 = mi.write_memory_gated("下周行程", "周三去上海出差",
                               category="C", agent_id="xi", importance=3)
    assert r1["ok"] is True

    r2 = mi.write_memory_gated("下周行程", "周三在家加班",
                               category="C", agent_id="xi", importance=3)
    assert r2["ok"] is False
    assert r2["reason"] == "conflict"
    assert r2["existing_value"] == "周三去上海出差"
    assert r2["new_value"] == "周三在家加班"

    # 未被静默覆盖
    entries = mi.list_memory("xi")
    assert len(entries) == 1
    assert entries[0].value == "周三去上海出差"


def test_session_write_limit():
    topics = ["生日", "通勤", "猫粮品牌", "周末旅行",
              "工作目标", "联系方式", "兴趣爱好", "睡眠习惯"]
    assert len(topics) == mi.MAX_WRITES_PER_SESSION

    for i, topic in enumerate(topics):
        r = mi.write_memory_gated(topic, f"内容{i}",
                                  category="C", agent_id="xi", importance=3)
        assert r["ok"] is True, (topic, r)

    r = mi.write_memory_gated("超额条目", "内容8",
                              category="C", agent_id="xi", importance=3)
    assert r["ok"] is False
    assert r["reason"] == "session_limit"

    # 未写入第9条
    entries = [e for e in mi.list_memory("xi") if e.category == "C"]
    assert len(entries) == mi.MAX_WRITES_PER_SESSION


def test_reset_session_writes_clears_per_agent_count():
    topics = ["生日", "通勤", "猫粮品牌", "周末旅行",
              "工作目标", "联系方式", "兴趣爱好", "睡眠习惯"]
    for i, topic in enumerate(topics):
        r = mi.write_memory_gated(topic, f"内容{i}",
                                  category="D", agent_id="xi", importance=3)
        assert r["ok"] is True, (topic, r)

    blocked = mi.write_memory_gated("再来一条", "内容", category="D", agent_id="xi", importance=3)
    assert blocked["ok"] is False
    assert blocked["reason"] == "session_limit"

    mi.reset_session_writes("xi")
    r = mi.write_memory_gated("再来一条", "内容", category="D", agent_id="xi", importance=3)
    assert r["ok"] is True
