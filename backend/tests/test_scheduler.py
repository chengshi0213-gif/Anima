#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_scheduler.py — 守藏每日 SOP 定时（M2a）相关单元测试 (pytest)

锁定：
  - result_to_text：把 AgentBase.run()/run_daily_sop() 的 dict 结果摊平成
    字符串（修复 _execute_task 对 output[:2000] 的潜在 TypeError）。
  - TaskScheduler.add_task_if_missing：按 name 去重的幂等注册（M2a/M2b/M10
    共用的"系统任务"注册模式）。
  - _execute_task 在 _run_fn 返回 dict 时仍能正确落 run_logs。
  - scholar_worker 暴露 M2a 所需的 DAILY_SOP_* 常量 + run_daily_sop。
  - websocket_server 启动流程接好了 add_task_if_missing + run_daily_sop
    特例路由（源码级检查，避免导入整个 websocket_server 重模块）。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_scheduler.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import scheduler as sched_mod  # noqa: E402
from scheduler import TaskScheduler, result_to_text  # noqa: E402
import scholar_worker as sw  # noqa: E402


@pytest.fixture
def sched(tmp_path, monkeypatch):
    """独立 tasks.json/run_logs.json，避免污染真实数据目录。"""
    monkeypatch.setattr(sched_mod, "TASKS_FILE", tmp_path / "tasks.json")
    monkeypatch.setattr(sched_mod, "LOGS_FILE", tmp_path / "run_logs.json")
    s = TaskScheduler()
    return s


# ── result_to_text ──────────────────────────────────────
def test_result_to_text_dict_with_summary():
    assert result_to_text({"status": "completed", "summary": "做完了"}) == "做完了"


def test_result_to_text_dict_with_error_no_summary():
    assert result_to_text({"status": "error", "error": "boom"}) == "boom"


def test_result_to_text_plain_string_passthrough():
    assert result_to_text("hello") == "hello"


# ── add_task_if_missing：M2a/M2b/M10 共用的幂等注册 ──────
def test_add_task_if_missing_creates_once(sched):
    t1 = sched.add_task_if_missing(sw.DAILY_SOP_TASK_NAME, "shoucang",
                                    sw.DAILY_SOP_TRIGGER, "cron", sw.DAILY_SOP_CRON)
    assert t1 is not None
    assert t1["agent"] == "shoucang"
    assert t1["enabled"] is True

    t2 = sched.add_task_if_missing(sw.DAILY_SOP_TASK_NAME, "shoucang",
                                    sw.DAILY_SOP_TRIGGER, "cron", sw.DAILY_SOP_CRON)
    assert t2 is None
    assert len(sched.list_tasks()) == 1


# ── _execute_task：dict 结果能正确落 run_logs ──────────────
def test_execute_task_handles_dict_result(sched):
    task = sched.add_task("测试任务", "shoucang", "do something", "cron", "04:00")

    async def fake_run_fn(agent, prompt):
        return {"status": "completed", "summary": "执行成功", "turn_count": 1}

    sched.set_run_fn(fake_run_fn)
    asyncio.run(sched._execute_task(task["id"]))

    logs = sched.list_logs(task["id"])
    assert len(logs) == 1
    assert logs[0]["ok"] is True
    assert logs[0]["output"] == "执行成功"
    assert sched.list_tasks()[0]["run_count"] == 1


def test_execute_task_handles_run_fn_exception(sched):
    task = sched.add_task("测试任务2", "shoucang", "do something", "cron", "04:00")

    async def boom_run_fn(agent, prompt):
        raise RuntimeError("挂了")

    sched.set_run_fn(boom_run_fn)
    asyncio.run(sched._execute_task(task["id"]))

    logs = sched.list_logs(task["id"])
    assert logs[0]["ok"] is False
    assert "挂了" in logs[0]["output"]


# ── scholar_worker：M2a 常量与方法存在 ─────────────────────
def test_daily_sop_constants_present():
    assert sw.DAILY_SOP_TASK_NAME == "守藏每日记忆整理"
    assert sw.DAILY_SOP_CRON == "04:00"
    assert sw.DAILY_SOP_TRIGGER
    assert hasattr(sw.ShoucangWorker, "run_daily_sop")


# ── websocket_server：启动流程接线检查（源码级，避免重导入）──
def test_websocket_server_wires_daily_sop_registration():
    src = (_BACKEND / "websocket_server.py").read_text("utf-8")
    assert "DAILY_SOP_TASK_NAME" in src
    assert "DAILY_SOP_TRIGGER" in src
    assert "DAILY_SOP_CRON" in src
    assert "add_task_if_missing" in src
    assert "run_daily_sop" in src
