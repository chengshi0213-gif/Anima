#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_pref_learning.py — 偏好学习管线（M10）单元测试

覆盖：
  - 信号采集：record_signal / list_pref_signals / get_signal_counts
  - 信号合法性校验：未知领域 / 未知信号类型
  - 规则写入：write_pref_rule 基本写入、近似文本合并、单领域≤8条淘汰
  - 注入文本：get_pref_rules_injection 按领域分组、无规则时为空
  - 房间判断（D8 最小版）：room.get_room_type / is_work_room
  - 工作房间门控：get_work_room_injection 按 agent + 房间类型双重门控
  - 周级 SOP：信号不足时直接 skip（不触发 LLM）
  - 调度：每周偏好学习 cron 可被正确解析
  - 工具定义：write_pref_rule / list_pref_signals 暴露给守藏

运行:
    cd E:\\AI\\workspace\\Anima\\backend
    python -m pytest tests/test_pref_learning.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import memory_injector as mi  # noqa: E402
from memory_sqlite import SQLiteMemoryBackend  # noqa: E402
import pref_learning  # noqa: E402
import room  # noqa: E402
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


# ── 信号采集 ──────────────────────────────────────────────────

def test_record_signal_and_list_pref_signals(sqlite_mem):
    r1 = pref_learning.record_signal("文案", "edit", original="超长广告语！！！",
                                      edited="一句话说清楚", note="改短了")
    r2 = pref_learning.record_signal("文案", "complaint", note="太啰嗦了")
    r3 = pref_learning.record_signal("文案", "accept", original="按原样采纳的文案")
    assert r1["ok"] is True and r2["ok"] is True and r3["ok"] is True

    signals = pref_learning.get_signals("文案")
    assert len(signals) == 3
    types = {s["signal_type"] for s in signals}
    assert types == {"edit", "complaint", "accept"}
    edit = next(s for s in signals if s["signal_type"] == "edit")
    assert edit["original"] == "超长广告语！！！"
    assert edit["edited"] == "一句话说清楚"


def test_record_signal_validates_domain_and_type(sqlite_mem):
    bad_domain = pref_learning.record_signal("绘画", "edit")
    assert bad_domain["ok"] is False

    bad_type = pref_learning.record_signal("文案", "rant")
    assert bad_type["ok"] is False


def test_get_signal_counts_returns_all_domains(sqlite_mem):
    pref_learning.record_signal("代码", "edit", original="a", edited="b")
    pref_learning.record_signal("代码", "edit", original="c", edited="d")

    counts = pref_learning.get_signal_counts()
    assert set(counts.keys()) == set(pref_learning.PREF_DOMAINS)
    assert counts["代码"] == 2
    assert counts["文案"] == 0


# ── 规则写入 / 合并 / 淘汰 ────────────────────────────────────

def test_write_pref_rule_basic(sqlite_mem):
    r = pref_learning.write_pref_rule("文案", "写文案时倾向短句、少用感叹号",
                                       source_ids=["sig1", "sig2"], agent_id="xi")
    assert r["ok"] is True
    assert r["merged"] is False

    rules = pref_learning.get_pref_rules("文案")
    assert len(rules) == 1
    assert rules[0]["rule"] == "写文案时倾向短句、少用感叹号"
    assert rules[0]["source_ids"] == "sig1,sig2"


def test_write_pref_rule_merges_similar(sqlite_mem):
    r1 = pref_learning.write_pref_rule("文案", "写文案时倾向短句、少用感叹号",
                                        source_ids=["sig1"], agent_id="xi")
    r2 = pref_learning.write_pref_rule("文案", "写文案时倾向短句，少用感叹号",
                                        source_ids=["sig1", "sig2"], agent_id="xi")
    assert r2["merged"] is True
    assert r2["id"] == r1["id"]

    rules = pref_learning.get_pref_rules("文案")
    assert len(rules) == 1
    assert rules[0]["source_ids"] == "sig1,sig2"


def test_invalid_domain_in_write_pref_rule(sqlite_mem):
    r = pref_learning.write_pref_rule("绘画", "随便一条规则")
    assert r["ok"] is False


def test_pref_rule_eviction_keeps_max_8_per_domain(sqlite_mem):
    rules_text = [
        "写代码时优先复用现有工具函数，不要重复造轮子",
        "命名变量使用语义化英文单词，避免拼音缩写",
        "函数注释只写为什么不写做什么",
        "提交前先跑一遍相关测试用例",
        "新增依赖前先确认是否已有等价库",
        "错误处理只在系统边界做，内部信任调用方",
        "避免新增配置开关，直接改代码",
        "重构时不引入新的抽象层，除非真的需要",
        "缩进和命名遵循项目现有风格约定",
    ]
    for i, text in enumerate(rules_text):
        importance = 1 if i == 0 else 5
        pref_learning.write_pref_rule("代码", text, agent_id="xi", importance=importance)

    rules = pref_learning.get_pref_rules("代码")
    assert len(rules) == 8
    assert all(r["rule"] != rules_text[0] for r in rules)


# ── 注入文本 ──────────────────────────────────────────────────

def test_get_pref_rules_injection_groups_by_domain(sqlite_mem):
    pref_learning.write_pref_rule("文案", "写文案时倾向短句", agent_id="xi")
    pref_learning.write_pref_rule("代码", "改代码时优先复用现有工具函数", agent_id="xi")

    injection = pref_learning.get_pref_rules_injection()
    assert "[文案]" in injection
    assert "写文案时倾向短句" in injection
    assert "[代码]" in injection
    assert "改代码时优先复用现有工具函数" in injection
    assert "[PPT]" not in injection
    assert "[命盘解读]" not in injection


def test_get_pref_rules_injection_empty_when_no_rules(sqlite_mem):
    assert pref_learning.get_pref_rules_injection() == ""


# ── 房间判断（D8 最小版）──────────────────────────────────────

def test_room_daily_when_no_active_project(monkeypatch):
    monkeypatch.setattr(mi, "get_active_project", lambda: None)
    assert room.get_room_type() == "daily"
    assert room.is_work_room() is False


def test_room_work_when_active_project_set(monkeypatch):
    monkeypatch.setattr(mi, "get_active_project", lambda: "myproj")
    assert room.get_room_type() == "work"
    assert room.is_work_room() is True


# ── 工作房间门控 ──────────────────────────────────────────────

def test_get_work_room_injection_gated_by_room_and_agent(sqlite_mem, monkeypatch):
    pref_learning.write_pref_rule("文案", "写文案时倾向短句", agent_id="xi")

    monkeypatch.setattr(mi, "get_active_project", lambda: None)
    assert pref_learning.get_work_room_injection("xi") == ""

    monkeypatch.setattr(mi, "get_active_project", lambda: "myproj")
    injection = pref_learning.get_work_room_injection("xi")
    assert "写文案时倾向短句" in injection

    assert pref_learning.get_work_room_injection("yiyi") == ""


# ── 周级 SOP：信号不足直接 skip ───────────────────────────────

def test_run_weekly_pref_learning_skips_when_insufficient_signals(sqlite_mem):
    worker = sw.ShoucangWorker()
    result = worker.run_weekly_pref_learning()
    assert result["status"] == "skipped"


# ── 调度 ──────────────────────────────────────────────────────

def test_weekly_pref_cron_is_valid():
    from scheduler import TaskScheduler
    trigger = TaskScheduler._make_trigger("cron", sw.WEEKLY_PREF_CRON)
    assert trigger is not None


# ── 工具定义暴露 ──────────────────────────────────────────────

def test_write_pref_rule_def_and_list_pref_signals_def_exposed():
    write_params = sw.WRITE_PREF_RULE_DEF["function"]["parameters"]["properties"]
    assert set(["domain", "rule", "source_ids", "importance"]).issubset(write_params.keys())

    list_params = sw.LIST_PREF_SIGNALS_DEF["function"]["parameters"]["properties"]
    assert set(["domain", "limit"]).issubset(list_params.keys())
