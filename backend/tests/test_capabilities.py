#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_capabilities.py — 记忆能力积木（M1）单元测试 (pytest)

验证 capabilities.py 的 _memory_cap：
  - tool_defs 含 remember/recall/forget 三个工具
  - dispatch 三条路径走通：写入 → 搜索可见 → 删除后不可见
  - category 校验：非 A/B/C/D 回落 C
  - 写入的 A/B/C/D 分类条目能被 read_for_agent("xi") 注入（白名单已扩展）

不依赖真实记忆库：把激活后端换成 tmp_path 下的独立 SQLite。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_capabilities.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import capabilities  # noqa: E402
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


@pytest.fixture
def memory_dispatch():
    comp = capabilities.build(["memory"], agent_id="xi")
    return comp


def test_memory_registered_in_factories_and_caps():
    assert "memory" in capabilities._FACTORIES
    from xi_worker import XiWorker
    assert "memory" in XiWorker.CAPS


def test_tool_defs_have_remember_recall_forget(memory_dispatch):
    names = {d["function"]["name"] for d in memory_dispatch["tool_defs"]}
    assert {"remember", "recall", "forget"} <= names
    for fn in memory_dispatch["dispatch"].values():
        assert callable(fn)


def test_fragment_covers_abcd_grading(memory_dispatch):
    text = "\n".join(memory_dispatch["fragments"])
    for marker in ("A 身份恒定", "B 偏好习惯", "C 近期状态", "D 关系记忆"):
        assert marker in text


def test_remember_recall_forget_roundtrip(memory_dispatch):
    dispatch = memory_dispatch["dispatch"]

    r = dispatch["remember"](key="下周行程", value="周三去上海出差", category="C")
    assert r["ok"] is True
    assert r["category"] == "C"

    found = dispatch["recall"](query="上海出差")
    assert any("上海出差" in e["value"] for e in found["results"])

    f = dispatch["forget"](key="下周行程")
    assert f["ok"] is True

    found2 = dispatch["recall"](query="上海出差")
    assert not any(e["key"] == "下周行程" for e in found2["results"])


def test_remember_invalid_category_falls_back_to_c(memory_dispatch):
    dispatch = memory_dispatch["dispatch"]
    r = dispatch["remember"](key="临时备注", value="无所谓的事", category="Z")
    assert r["category"] == "C"


def test_forget_unknown_key_returns_not_ok(memory_dispatch):
    dispatch = memory_dispatch["dispatch"]
    r = dispatch["forget"](key="不存在的key")
    assert r["ok"] is False


def test_remembered_entries_are_injected_for_xi(memory_dispatch):
    dispatch = memory_dispatch["dispatch"]
    dispatch["remember"](key="不吃香菜", value="点菜时记得避开香菜", category="B")
    dispatch["remember"](key="承诺", value="答应下周陪他看一次方案细化", category="D")

    mi.invalidate_cache("xi")
    injection = mi.get_memory_injection("xi")
    assert "不吃香菜" in injection
    assert "答应下周陪他看一次方案细化" in injection
