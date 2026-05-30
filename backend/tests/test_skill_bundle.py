#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_skill_bundle.py — 多文件 bundle 技能 + agent 绑定 单元测试 (pytest)

以随后端分发、首次运行自动安装的「命理巨师 minglijushi」(绑定晞 yiyi) 为基准，
锁定 bundle 识别、agent 注入门控、reference 渐进加载与路径穿越防护。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_skill_bundle.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import skill_manager as sm  # noqa: E402

SID = "minglijushi"
BOUND = "yiyi"       # 晞
OTHER = "tianyuan"   # 陶朱


def test_bundle_detected():
    assert sm._is_bundle(SID) is True
    skill = sm.get_skill(SID)
    assert skill["type"] == "bundle"
    assert skill["agents"] == [BOUND]
    assert "ziwei-paipan.md" in sm.list_skill_references(SID)


def test_prompt_agent_gating():
    # 绑定 agent 可取到工作流正文
    assert len(sm.get_skill_prompt(SID, agent_id=BOUND)) > 100
    # 未绑定 agent / 未指定 agent → 拒绝注入
    assert sm.get_skill_prompt(SID, agent_id=OTHER) == ""
    assert sm.get_skill_prompt(SID) == ""


def test_reference_progressive_load():
    ref = sm.load_skill_reference(SID, "ziwei-paipan.md", agent_id=BOUND)
    assert ref and "命宫" in ref
    # 未授权 agent 不能加载
    assert sm.load_skill_reference(SID, "ziwei-paipan.md", agent_id=OTHER) is None


def test_reference_path_traversal_blocked():
    assert sm.load_skill_reference(SID, "../../config.py", agent_id=BOUND) is None
    assert sm.load_skill_reference(SID, "..\\..\\config.py", agent_id=BOUND) is None
    assert sm.load_skill_reference(SID, "nonexistent.md", agent_id=BOUND) is None


def test_agent_skill_visibility():
    assert SID in sm.get_agent_skills(BOUND)
    assert SID not in sm.get_agent_skills(OTHER)
    assert any(s["id"] == SID for s in sm.list_skills(agent_id=BOUND))
    assert not any(s["id"] == SID for s in sm.list_skills(agent_id=OTHER))


def test_global_single_skills_unaffected():
    # 现有全局单文件技能：任何 agent + 无 agent 调用都应可取
    assert len(sm.get_skill_prompt("emotional_support")) > 0
    assert len(sm.get_skill_prompt("emotional_support", agent_id=OTHER)) > 0
    assert "emotional_support" in sm.get_agent_skills(OTHER)
    assert sm.get_skill("emotional_support")["type"] == "single"


def test_bind_rebind_roundtrip():
    # 改绑后再绑回，确保 bind API 生效且可逆
    try:
        r = sm.bind_skill_to_agents(SID, [BOUND, OTHER])
        assert r["ok"] and set(r["agents"]) == {BOUND, OTHER}
        assert SID in sm.get_agent_skills(OTHER)
    finally:
        sm.bind_skill_to_agents(SID, [BOUND])  # 还原
    assert sm.get_skill(SID)["agents"] == [BOUND]
