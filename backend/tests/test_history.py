#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_history.py — 会话历史持久化（修复"多轮只剩最后一轮"的回归）

验证 WorkerServer._record_turn：
  - 多轮对话整段累积，而非每轮覆盖（核心回归）。
  - 进程重启后续接旧会话：先从 DB 捞回旧消息再追加，不丢历史。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_history.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from search_engine import SearchEngine  # noqa: E402
from ws_manager import WorkerServer      # noqa: E402


class _FakeWorker:
    name = "executor"
    model = "m"


def _make_server(tmp_path):
    se = SearchEngine(tmp_path / "sessions.db")
    return WorkerServer(_FakeWorker(), se, None, None), se


def test_multi_turn_accumulates_not_overwrites(tmp_path):
    srv, se = _make_server(tmp_path)
    sid = "executor-1"
    srv._record_turn(sid, "第一问", "第一答")
    srv._record_turn(sid, "第二问", "第二答")
    srv._record_turn(sid, "第三问", "第三答")

    msgs = se.get_session_messages(sid)
    contents = [m["content"] for m in msgs]
    # 三轮 user+assistant 全部在，而不是只剩最后一轮
    assert contents == ["第一问", "第一答", "第二问", "第二答", "第三问", "第三答"]


def test_resume_after_restart_keeps_history(tmp_path):
    # 第一段进程：记两轮
    srv1, se1 = _make_server(tmp_path)
    sid = "executor-9"
    srv1._record_turn(sid, "Q1", "A1")
    srv1._record_turn(sid, "Q2", "A2")
    se1.close()

    # 模拟重启：全新 server + 全新内存累积，但指向同一个 DB
    se2 = SearchEngine(tmp_path / "sessions.db")
    srv2 = WorkerServer(_FakeWorker(), se2, None, None)
    srv2._record_turn(sid, "Q3", "A3")

    contents = [m["content"] for m in se2.get_session_messages(sid)]
    assert contents == ["Q1", "A1", "Q2", "A2", "Q3", "A3"]


def test_list_sessions_summary_is_last_answer(tmp_path):
    srv, se = _make_server(tmp_path)
    sid = "executor-5"
    srv._record_turn(sid, "问候", "你好")
    srv._record_turn(sid, "再问", "最终答复")
    sessions = se.list_sessions(limit=10)
    rec = next(s for s in sessions if s["session_id"] == sid)
    assert rec["summary"] == "最终答复"
