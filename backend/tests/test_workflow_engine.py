#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_workflow_engine.py — 工作流执行引擎（M10 Part 2-4）单元测试

不触网：用假 worker / 假 generator。验证：
  - 叶子：顺序执行 + pass_context、未知 agent 报错。
  - retry：失败 N 次后成功；timeout：超时计为失败。
  - on_error=stop：失败后停止后续步骤。
  - parallel / loop（stop_keyword 提前退出）。
  - condition：keyword 直配 + mode="ai" 模型判定。
  - router：AI 多路选路（含模型不可用兜底走第一条）。
  - human：无 gate 默认放行；reject 终止；approve+note 注入下游。
  - taozu：运行时把目标编译成子图并执行。
  - emit：事件流被逐步吐出。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_workflow_engine.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from workflow_engine import WorkflowRunner, run_workflow  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── 假 worker / server ──────────────────────────────────────────────────────

class _Worker:
    def __init__(self, fn):
        self._fn = fn
    async def run(self, prompt):
        return await self._fn(prompt)


class _Srv:
    def __init__(self, fn):
        self.worker = _Worker(fn)


def _echo_srv(tag="ok"):
    async def fn(p):
        return {"summary": f"{tag}:{p[-30:]}"}
    return _Srv(fn)


def _fail_then_ok_srv(n_fails):
    state = {"n": 0}
    async def fn(p):
        if state["n"] < n_fails:
            state["n"] += 1
            raise RuntimeError(f"boom{state['n']}")
        return {"summary": "终于成功"}
    return _Srv(fn)


def _slow_srv(delay):
    async def fn(p):
        await asyncio.sleep(delay)
        return {"summary": "慢但成了"}
    return _Srv(fn)


class _FakeGen:
    """按需返回固定文本；记录被问了什么。"""
    def __init__(self, content):
        self._content = content
        self.calls = []
    async def _call_api(self, messages, tools=None, stream=False):
        self.calls.append(messages)
        c = self._content(messages) if callable(self._content) else self._content
        return {"content": c}


def _servers():
    return {
        "xi": _echo_srv("xi"),
        "writer": _echo_srv("writer"),
        "critic": _echo_srv("critic"),
        "executor": _echo_srv("exec"),
        "researcher": _echo_srv("res"),
    }


# ── 叶子 ────────────────────────────────────────────────────────────────────

def test_sequential_passes_context():
    steps = [
        {"type": "sequential", "agent": "writer", "prompt": "第一步"},
        {"type": "sequential", "agent": "critic", "prompt": "第二步", "pass_context": True},
    ]
    out = _run(run_workflow(steps, _servers()))
    assert out["ok"] is True
    # 第二步的 prompt 里应带上一步输出
    r2 = out["results"][1]
    assert r2["agent"] == "critic"
    assert "writer:" in r2["output"]  # critic echo 了带上下文的 prompt


def test_unknown_agent_errors_but_continues():
    steps = [{"agent": "ghost", "prompt": "x"},
             {"agent": "xi", "prompt": "y"}]
    out = _run(run_workflow(steps, _servers()))
    assert out["results"][0]["ok"] is False
    assert "未知 agent" in out["results"][0]["output"]
    assert out["results"][1]["ok"] is True  # 默认 on_error=continue


# ── retry / timeout / on_error ──────────────────────────────────────────────

def test_retry_recovers():
    srv = {"executor": _fail_then_ok_srv(2)}
    steps = [{"agent": "executor", "prompt": "干活", "retry": 2}]
    out = _run(run_workflow(steps, srv))
    r = out["results"][0]
    assert r["ok"] is True
    assert r["attempts"] == 3
    assert r["output"].endswith("终于成功") or "终于成功" in r["output"]


def test_retry_exhausted_fails():
    srv = {"executor": _fail_then_ok_srv(5)}
    steps = [{"agent": "executor", "prompt": "干活", "retry": 1}]
    out = _run(run_workflow(steps, srv))
    r = out["results"][0]
    assert r["ok"] is False
    assert r["attempts"] == 2
    assert "执行错误" in r["output"]


def test_timeout_counts_as_failure():
    srv = {"executor": _slow_srv(0.3)}
    steps = [{"agent": "executor", "prompt": "慢", "timeout": 0.05}]
    out = _run(run_workflow(steps, srv))
    r = out["results"][0]
    assert r["ok"] is False
    assert "超时" in r["output"]


def test_on_error_stop_halts():
    srv = {"executor": _fail_then_ok_srv(9), "xi": _echo_srv("xi")}
    steps = [
        {"agent": "executor", "prompt": "会失败", "on_error": "stop"},
        {"agent": "xi", "prompt": "不该执行"},
    ]
    out = _run(run_workflow(steps, srv))
    assert out["stopped"] is True
    assert len(out["results"]) == 1  # 第二步没跑


# ── parallel / loop ─────────────────────────────────────────────────────────

def test_parallel_runs_all_branches():
    steps = [{"type": "parallel", "branches": [
        {"agent": "writer", "prompt": "A"},
        {"agent": "critic", "prompt": "B"},
    ]}]
    out = _run(run_workflow(steps, _servers()))
    r = out["results"][0]
    assert r["type"] == "parallel"
    assert len(r["branches"]) == 2
    assert "writer:" in r["output"] and "critic:" in r["output"]


def test_loop_stops_on_keyword():
    # worker 第三次返回里带"完成"
    state = {"n": 0}
    async def fn(p):
        state["n"] += 1
        return {"summary": "完成" if state["n"] >= 2 else "还在继续"}
    srv = {"executor": _Srv(fn)}
    steps = [{"type": "loop", "max_iter": 5, "stop_keyword": "完成",
              "step": {"agent": "executor", "prompt": "迭代"}}]
    out = _run(run_workflow(steps, srv))
    r = out["results"][0]
    assert r["iterations"] == 2  # 第二轮命中 stop


# ── condition ───────────────────────────────────────────────────────────────

def test_condition_keyword_match():
    steps = [
        {"agent": "writer", "prompt": "产出包含 通过 字样"},
        {"type": "condition", "keyword": "通过",
         "true_step": {"agent": "critic", "prompt": "命中分支"},
         "false_step": {"agent": "xi", "prompt": "未命中分支"}},
    ]
    out = _run(run_workflow(steps, _servers()))
    cond = out["results"][1]
    assert cond["matched"] is True
    assert cond["agent"] == "critic"


def test_condition_ai_mode():
    gen = _FakeGen("是")
    steps = [
        {"agent": "writer", "prompt": "随便写点"},
        {"type": "condition", "mode": "ai", "question": "内容是否合格",
         "true_step": {"agent": "critic", "prompt": "合格分支"},
         "false_step": {"agent": "xi", "prompt": "不合格分支"}},
    ]
    out = _run(run_workflow(steps, _servers(), generator=gen))
    cond = out["results"][1]
    assert cond["by"] == "ai"
    assert cond["matched"] is True
    assert cond["agent"] == "critic"


# ── router ──────────────────────────────────────────────────────────────────

def test_router_ai_picks_label():
    gen = _FakeGen("投诉")
    steps = [{"type": "router", "question": "用户意图是哪类", "routes": [
        {"label": "退款", "step": {"agent": "xi", "prompt": "处理退款"}},
        {"label": "投诉", "step": {"agent": "critic", "prompt": "处理投诉"}},
    ]}]
    out = _run(run_workflow(steps, _servers(), generator=gen))
    r = out["results"][0]
    assert r["chosen"] == "投诉"
    assert r["agent"] == "critic"


def test_router_falls_back_to_first_when_no_generator():
    steps = [{"type": "router", "routes": [
        {"label": "甲", "step": {"agent": "xi", "prompt": "甲路"}},
        {"label": "乙", "step": {"agent": "critic", "prompt": "乙路"}},
    ]}]
    out = _run(run_workflow(steps, _servers()))  # 无 generator
    r = out["results"][0]
    assert r["chosen"] == "甲"
    assert r["agent"] == "xi"


# ── human ───────────────────────────────────────────────────────────────────

def test_human_auto_approves_without_gate():
    steps = [
        {"agent": "writer", "prompt": "产出"},
        {"type": "human", "message": "请审核"},
        {"agent": "xi", "prompt": "继续"},
    ]
    out = _run(run_workflow(steps, _servers()))
    h = out["results"][1]
    assert h["action"] == "approve"
    assert h["auto_approved"] is True
    assert len(out["results"]) == 3  # 后续照常执行


def test_human_reject_halts():
    async def gate(i, msg):
        return {"action": "reject", "note": "质量不行"}
    steps = [
        {"agent": "writer", "prompt": "产出"},
        {"type": "human", "message": "请审核"},
        {"agent": "xi", "prompt": "不该执行"},
    ]
    out = _run(run_workflow(steps, _servers(), gate=gate))
    assert out["stopped"] is True
    assert "质量不行" in out["stop_reason"]
    assert len(out["results"]) == 2


def test_human_approve_note_feeds_downstream():
    async def gate(i, msg):
        return {"action": "approve", "note": "补充：重点写性价比"}
    steps = [
        {"agent": "writer", "prompt": "初稿"},
        {"type": "human", "message": "审核"},
        {"agent": "critic", "prompt": "据此润色", "pass_context": True},
    ]
    out = _run(run_workflow(steps, _servers(), gate=gate))
    last = out["results"][2]
    assert "重点写性价比" in last["output"]


# ── taozu 动态展开 ──────────────────────────────────────────────────────────

def test_taozu_expands_and_runs_subgraph():
    plan = {"name": "子图", "steps": [
        {"agent": "researcher", "prompt": "查"},
        {"agent": "writer", "prompt": "写"},
    ], "explanation": "先查后写"}
    gen = _FakeGen(json.dumps(plan, ensure_ascii=False))
    steps = [{"type": "taozu", "goal": "调研并写报告"}]
    out = _run(run_workflow(steps, _servers(), generator=gen))
    r = out["results"][0]
    assert r["type"] == "taozu"
    assert r["name"] == "子图"
    assert len(r["sub_results"]) == 2
    assert "writer:" in r["output"]


def test_taozu_without_generator_is_graceful():
    steps = [{"type": "taozu", "goal": "随便"}]
    out = _run(run_workflow(steps, _servers()))  # 无 generator
    r = out["results"][0]
    assert r["type"] == "taozu"
    assert "不可用" in r["output"]


# ── emit 事件流 ─────────────────────────────────────────────────────────────

def test_emit_streams_events():
    events = []
    async def emit(ev):
        events.append(ev["event"])
    steps = [{"agent": "writer", "prompt": "A"}, {"agent": "critic", "prompt": "B"}]
    _run(run_workflow(steps, _servers(), emit=emit))
    assert events[0] == "start"
    assert events[-1] == "done"
    assert events.count("step_start") == 2
    assert events.count("step_done") == 2
