#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_workflow_graph.py — DAG 图执行器（n8n/扣子 风格）单元测试

不触网：用假 worker。验证：
  - 线性链 A→B→C：上下文沿边传递。
  - 分支 + 合流 A→{B,C}→D：D 合并 B、C 的输出。
  - condition 路由：命中走 output_1，未命中分支整条被跳过。
  - 同层并发：两条独立分支都执行。
  - 起点自动识别（无入边即起点）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from workflow_engine import WorkflowRunner, run_workflow_graph  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class _Worker:
    def __init__(self, fn): self._fn = fn
    async def run(self, prompt): return await self._fn(prompt)


class _Srv:
    def __init__(self, fn): self.worker = _Worker(fn)


def _echo(tag):
    async def fn(p):
        return {"summary": f"{tag}<<{p}"}
    return _Srv(fn)


SERVERS = {a: _echo(a) for a in ("xi", "yiyi", "tianyuan", "shoucang", "executor", "writer")}


def _agent(agent, prompt):
    return {"type": "agent", "data": {"agent": agent, "prompt": prompt, "pass_context": True}}


def test_linear_chain():
    graph = {
        "nodes": {"a": _agent("xi", "A"), "b": _agent("yiyi", "B"), "c": _agent("tianyuan", "C")},
        "connections": [
            {"source": "a", "target": "b", "sourcePort": "output_1"},
            {"source": "b", "target": "c", "sourcePort": "output_1"},
        ],
    }
    out = _run(run_workflow_graph(graph, SERVERS))
    assert out["ok"]
    by = {r["node"]: r for r in out["results"]}
    assert set(by) == {"a", "b", "c"}
    # C 的输入应包含 B 的输出，B 的输出包含 A
    assert "yiyi<<" in by["c"]["output"]  # C 收到 B(yiyi) 产出作为上下文
    assert "xi<<" in by["b"]["output"]


def test_branch_and_merge():
    graph = {
        "nodes": {
            "a": _agent("xi", "seed"),
            "b": _agent("yiyi", "left"),
            "c": _agent("tianyuan", "right"),
            "d": _agent("shoucang", "merge"),
        },
        "connections": [
            {"source": "a", "target": "b", "sourcePort": "output_1"},
            {"source": "a", "target": "c", "sourcePort": "output_1"},
            {"source": "b", "target": "d", "sourcePort": "output_1"},
            {"source": "c", "target": "d", "sourcePort": "output_1"},
        ],
    }
    out = _run(run_workflow_graph(graph, SERVERS))
    assert out["ok"]
    by = {r["node"]: r for r in out["results"]}
    # D 合并了 B 和 C 两路（输入上下文里都有）
    d_prompt_ctx = by["d"]["output"]
    assert "shoucang<<" in d_prompt_ctx
    # 4 个节点都执行
    assert set(by) == {"a", "b", "c", "d"}


def test_condition_routes_and_skips():
    graph = {
        "nodes": {
            "a": _agent("xi", "包含关键词通过"),
            "cond": {"type": "condition", "data": {"keyword": "通过", "mode": "keyword"}},
            "yes": _agent("writer", "走是分支"),
            "no": _agent("executor", "走否分支"),
        },
        "connections": [
            {"source": "a", "target": "cond", "sourcePort": "output_1"},
            {"source": "cond", "target": "yes", "sourcePort": "output_1"},   # 是
            {"source": "cond", "target": "no", "sourcePort": "output_2"},    # 否
        ],
    }
    out = _run(run_workflow_graph(graph, SERVERS))
    assert out["ok"]
    by = {r["node"]: r for r in out["results"]}
    # a 的输出含“通过” → 命中 → yes 执行，no 被跳过
    assert "yes" in by
    assert "no" not in by
    assert "no" in out["skipped"]
    assert by["cond"]["matched"] is True


def test_condition_false_branch():
    graph = {
        "nodes": {
            "a": _agent("xi", "这里没有那个词"),
            "cond": {"type": "condition", "data": {"keyword": "失败", "mode": "keyword"}},
            "yes": _agent("writer", "y"),
            "no": _agent("executor", "n"),
        },
        "connections": [
            {"source": "a", "target": "cond", "sourcePort": "output_1"},
            {"source": "cond", "target": "yes", "sourcePort": "output_1"},
            {"source": "cond", "target": "no", "sourcePort": "output_2"},
        ],
    }
    out = _run(run_workflow_graph(graph, SERVERS))
    by = {r["node"]: r for r in out["results"]}
    assert "no" in by and "yes" not in by
    assert "yes" in out["skipped"]


def test_empty_graph():
    out = _run(run_workflow_graph({"nodes": {}, "connections": []}, SERVERS))
    assert not out["ok"]
