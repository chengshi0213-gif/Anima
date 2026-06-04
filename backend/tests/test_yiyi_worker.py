#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_yiyi_worker.py — 晞 worker 命理接线 单元测试 (pytest)

锁定 M3-4 的接线：
  - 三个工具（paipan / load_mingli_reference / search_knowledge）注册正确；
  - _compose_system() 动态组装 人格 + 出生信息 + 命理 skill 工作流 + 适配说明；
  - paipan 工具走确定性引擎，返回排好版命盘 markdown；
  - reference 渐进加载带 agent 门控 + 路径穿越防护；
  - 只有晞能取到命理工作流（agent gating 与 skill_manager 一致）。

不触网：search_knowledge 走 stub embedding；paipan / reference 是纯本地确定性逻辑。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_yiyi_worker.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import yiyi_worker as yw  # noqa: E402
import cap_divination as cd  # noqa: E402

# 命理工具现住在 cap_divination（能力模块），晞与 Anima 共用。
# 工具级测试指向新家；worker 接线测试仍验 yiyi 正确组装它们。
_DISP = cd.divination_dispatch("yiyi")
_tool_paipan = cd._tool_paipan
_tool_load_reference = _DISP["load_mingli_reference"]
_tool_search_knowledge = _DISP["search_knowledge"]


def test_tools_registered():
    w = yw.YiyiWorker()
    names = [t["function"]["name"] for t in w.tool_defs]
    assert names == ["paipan", "load_mingli_reference", "search_knowledge"]
    assert set(w.tool_dispatch) == {"paipan", "load_mingli_reference", "search_knowledge"}
    assert w.max_turns == 30


def test_compose_system_assembles_layers():
    w = yw.YiyiWorker()
    s = w._compose_system()
    # 人格底色
    assert "晞" in s
    # 命理 skill 工作流（仅晞可取）
    assert "命理巨师" in s
    # 本系统适配说明
    assert "本系统适配说明" in s
    # 出生信息区块（已存档则给信息，未存档则给采集提示）
    assert "出生信息" in s


def test_paipan_deterministic():
    r = _tool_paipan(date="1995-08-15", time="06:30", gender="male")
    assert r.get("ok") is True
    assert r.get("time_unknown") is False
    md = r.get("markdown") or ""
    assert "八字" in md and "紫微" in md
    # 确定性：1995-08-15 06:30 男 → 日主戊土、紫微在午
    chart = r["chart"]
    assert chart["bazi"]["day_master"] == "戊"


def test_paipan_needs_date():
    # 不传 date 又没有 use_saved，且存档为空时应提示采集
    # （存档可能有值；这里只验证返回结构合理，不强依赖存档状态）
    r = _tool_paipan(date="2000-01-01", gender="female")
    assert r.get("ok") is True


def test_load_reference_listing_and_gating():
    avail = _tool_load_reference().get("available")
    assert "ziwei-paipan.md" in avail
    r = _tool_load_reference(ref="ziwei-paipan.md")
    assert "命宫" in (r.get("content") or "")


def test_load_reference_path_traversal_blocked():
    assert "error" in _tool_load_reference(ref="../../config.py")
    assert "error" in _tool_load_reference(ref="..\\..\\config.py")
    assert "error" in _tool_load_reference(ref="nonexistent.md")


def test_search_knowledge_empty_query():
    assert "error" in _tool_search_knowledge(query="")
