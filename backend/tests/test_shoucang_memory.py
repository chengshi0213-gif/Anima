#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_shoucang_memory.py — 守藏每日记忆闭环（M5）单元测试 (pytest)

验证「无 Obsidian 也能闭环」的本地替换手段：
  守藏 remember() → memory_injector.write_memory → SQLite 后端
  → 下次对话 get_memory_injection 注入到各人格 system prompt。

不依赖 Obsidian、不触网：把激活后端隔离到 tmp_path 的 SQLite。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_shoucang_memory.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import memory_injector as mi  # noqa: E402
from memory_sqlite import SQLiteMemoryBackend  # noqa: E402
import scholar_worker as sw  # noqa: E402


@pytest.fixture(autouse=True)
def sqlite_mem(tmp_path, monkeypatch):
    """把激活后端换成 tmp 下的独立 SQLite，清注入缓存。"""
    backend = SQLiteMemoryBackend(tmp_path / "mem.db")
    monkeypatch.setattr(mi, "_backend", backend)
    mi.invalidate_cache()
    yield backend
    mi.invalidate_cache()


def test_remember_then_injected_global():
    """全局记忆（agent_id 留空）应注入到所有人格。"""
    r = sw._remember("职业", "独立开发者", category="user_profile")
    assert r["ok"] is True
    assert r["agent_id"] is None      # 空串/None → 全局

    # user_profile 在四人格的可见分类里 → 都能读到
    for agent in ("xi", "yiyi", "tianyuan", "shoucang"):
        mi.invalidate_cache()
        text = mi.get_memory_injection(agent)
        assert "独立开发者" in text, f"{agent} 未注入全局记忆"


def test_remember_agent_scoped_no_leak():
    """晞的情感记忆不应泄露给陶朱。"""
    sw._remember("近期情绪", "因发布焦虑", category="emotional", agent_id="yiyi")

    mi.invalidate_cache()
    yiyi_text = mi.get_memory_injection("yiyi")
    assert "因发布焦虑" in yiyi_text

    mi.invalidate_cache()
    tianyuan_text = mi.get_memory_injection("tianyuan")
    assert "因发布焦虑" not in tianyuan_text


def test_remember_upsert_same_key():
    """同一 key 再写是更新而非堆重复条目。"""
    r1 = sw._remember("常驻城市", "上海", category="user_profile")
    r2 = sw._remember("常驻城市", "北京", category="user_profile")
    assert r1["id"] == r2["id"]        # 同 id = upsert

    listing = sw._list_memory()
    keys = [e["key"] for e in listing["entries"]]
    assert keys.count("常驻城市") == 1
    val = next(e["value"] for e in listing["entries"] if e["key"] == "常驻城市")
    assert val == "北京"


def test_remember_validation_and_clamp():
    """空 key/value 拒绝；非法 category 回落 general；importance 夹到 1-5。"""
    assert "error" in sw._remember("", "x")
    assert "error" in sw._remember("k", "")

    r = sw._remember("k1", "v1", category="不存在的分类", importance=99)
    assert r["category"] == "general"

    entry = next(e for e in sw._list_memory()["entries"] if e["key"] == "k1")
    assert entry["importance"] == 5    # 99 夹到 5


def test_list_memory_tool():
    """list_memory 返回结构正确，可按 agent 过滤（全局 + 该 agent 私有）。"""
    sw._remember("g", "全局事实", category="user_profile")
    sw._remember("b", "在做 SaaS", category="business", agent_id="tianyuan")

    all_entries = sw._list_memory()
    assert all_entries["total"] == 2

    ty = sw._list_memory("tianyuan")          # 全局 + tianyuan 私有
    keys = {e["key"] for e in ty["entries"]}
    assert keys == {"g", "b"}


def test_shoucang_has_memory_tools():
    """守藏 worker 必须挂载 remember / list_memory 工具。"""
    assert sw.REMEMBER_DEF["function"]["name"] == "remember"
    assert sw.LIST_MEMORY_DEF["function"]["name"] == "list_memory"

    worker = sw.ShoucangWorker()
    tool_names = {d["function"]["name"] for d in worker.tool_defs}
    assert "remember" in tool_names
    assert "list_memory" in tool_names
    assert callable(worker.tool_dispatch["remember"])
    assert callable(worker.tool_dispatch["list_memory"])
