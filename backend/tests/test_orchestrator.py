#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_orchestrator.py — 陶朱编排层（M6）单元测试 (pytest)

不触网、不调真模型：把子员工实例替换成 FakeAgent（async run 返回固定摘要），
验证 delegate 的派活/校验/线程跑循环、list_subagents 形状、
共享 tool_defs/dispatch、以及陶朱 worker 确实挂载了 delegate/list_subagents。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_orchestrator.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import orchestrator as orch  # noqa: E402


class _FakeAgent:
    """假子员工：async run 立刻返回固定结果，记录收到的 task。"""
    def __init__(self):
        self.last_task = None
        self.last_model = None
        self.last_project = "__unset__"

    async def run(self, task, model=None, **kw):
        self.last_task = task
        self.last_model = model
        self.last_project = kw.get("project")
        return {
            "status": "completed",
            "summary": f"已完成: {task[:20]}",
            "files_changed": ["out.md"],
            "turn_count": 4,
        }


@pytest.fixture(autouse=True)
def _clear_instances(monkeypatch):
    """每个测试用全新的实例缓存 + 清空派活链上下文，避免污染。"""
    monkeypatch.setattr(orch, "_instances", {})
    if hasattr(orch._local, "ctx"):
        del orch._local.ctx
    yield
    if hasattr(orch._local, "ctx"):
        del orch._local.ctx


def test_list_subagents_shape():
    out = orch.list_subagents()
    roles = {s["role"] for s in out["subagents"]}
    assert roles == {"executor", "writer", "reader", "critic",
                     "researcher", "analyst", "product_manager"}
    assert all(s["description"] for s in out["subagents"])


def test_delegate_unknown_role():
    r = orch.delegate("ceo", "做点啥")
    assert "error" in r and "未知子员工" in r["error"]


def test_delegate_empty_task():
    r = orch.delegate("executor", "   ")
    assert "error" in r and "task" in r["error"]


def test_delegate_runs_subagent(monkeypatch):
    fake = _FakeAgent()
    monkeypatch.setattr(orch, "_get_subagent", lambda role, project=None: fake)

    r = orch.delegate("executor", "重构登录模块", context="项目在 E:/app")
    assert r["role"] == "executor"
    assert r["status"] == "completed"
    assert "已完成" in r["summary"]
    assert r["files_changed"] == ["out.md"]
    assert r["turns"] == 4
    # context 应拼进 task 交给子员工
    assert "背景" in fake.last_task and "重构登录模块" in fake.last_task


def test_delegate_subagent_exception(monkeypatch):
    class _Boom:
        async def run(self, task, model=None, **kw):
            raise RuntimeError("炸了")
    monkeypatch.setattr(orch, "_get_subagent", lambda role, project=None: _Boom())
    r = orch.delegate("writer", "写篇文案")
    assert r["status"] == "error"
    assert "炸了" in r["summary"]


def test_build_dispatch_and_tool_defs():
    names = {d["function"]["name"] for d in orch.ORCHESTRATION_TOOL_DEFS}
    assert names == {"delegate", "delegate_parallel", "list_subagents"}
    d = orch.build_orchestration_dispatch()
    assert set(d) == {"delegate", "delegate_parallel", "list_subagents"}
    assert callable(d["delegate"]) and callable(d["list_subagents"])
    assert callable(d["delegate_parallel"])
    # delegate 工具的 enum 与注册表一致
    deleg = next(x for x in orch.ORCHESTRATION_TOOL_DEFS
                 if x["function"]["name"] == "delegate")
    enum = set(deleg["function"]["parameters"]["properties"]["role"]["enum"])
    assert enum == set(orch.SUBAGENT_FACTORIES)


def test_tianyuan_has_orchestration_tools():
    from tianyuan_worker import TianyuanWorker
    w = TianyuanWorker()
    tool_names = {d["function"]["name"] for d in w.tool_defs}
    assert "delegate" in tool_names
    assert "list_subagents" in tool_names
    assert callable(w.tool_dispatch["delegate"])
    assert callable(w.tool_dispatch["list_subagents"])


# ── M8：新角色 + 受控递归护栏 ──────────────────────────────────────

def test_new_roles_registered():
    for role in ("researcher", "analyst", "product_manager"):
        assert role in orch.SUBAGENT_FACTORIES
        mod, cls, desc = orch.SUBAGENT_FACTORIES[role]
        assert mod and cls and desc


def test_restricted_delegate_rejects_outside_whitelist(monkeypatch):
    """负责人型子员工只能派白名单内角色。"""
    fake = _FakeAgent()
    monkeypatch.setattr(orch, "_get_subagent", lambda role, project=None: fake)
    allowed = {"executor", "critic"}
    # 白名单内：放行
    ok = orch.delegate("executor", "干活", allowed_roles=allowed)
    assert ok["status"] == "completed"
    # 白名单外：拒绝，且不会真的实例化/运行
    bad = orch.delegate("writer", "写文案", allowed_roles=allowed)
    assert "error" in bad and "无权" in bad["error"]


def test_delegate_depth_cap(monkeypatch):
    """深度达到 _MAX_DEPTH 时再派活被拒（防递归失控）。"""
    fake = _FakeAgent()
    monkeypatch.setattr(orch, "_get_subagent", lambda role, project=None: fake)
    # 模拟"当前已在最大深度的子员工线程里"
    orch._local.ctx = {"shared": {"count": 0, "max": 16, "lock": __import__("threading").Lock()},
                       "depth": orch._MAX_DEPTH}
    r = orch.delegate("executor", "再往下派")
    assert "error" in r and "深度" in r["error"]


def test_delegate_tree_budget(monkeypatch):
    """单次任务派活次数达到上限后被拒（防成本失控）。"""
    fake = _FakeAgent()
    monkeypatch.setattr(orch, "_get_subagent", lambda role, project=None: fake)
    shared = {"count": orch._MAX_TREE_DELEGATIONS, "max": orch._MAX_TREE_DELEGATIONS,
              "lock": __import__("threading").Lock()}
    orch._local.ctx = {"shared": shared, "depth": 0}
    r = orch.delegate("executor", "再派一个")
    assert "error" in r and "上限" in r["error"]


def test_lead_delegate_tool_defs_enum():
    defs = orch.lead_delegate_tool_defs({"executor", "critic"})
    assert len(defs) == 1
    d = defs[0]
    assert d["function"]["name"] == "delegate"
    enum = set(d["function"]["parameters"]["properties"]["role"]["enum"])
    assert enum == {"executor", "critic"}


def test_delegate_passes_explicit_project(monkeypatch):
    """显式 project 透传给子员工 run()。"""
    fake = _FakeAgent()
    monkeypatch.setattr(orch, "_get_subagent", lambda role, project=None: fake)
    orch.delegate("executor", "干活", project="登录重构")
    assert fake.last_project == "登录重构"


def test_delegate_falls_back_to_active_project(monkeypatch):
    """不传 project 时回退到当前活跃项目（项目级记忆）。"""
    fake = _FakeAgent()
    monkeypatch.setattr(orch, "_get_subagent", lambda role, project=None: fake)
    import memory_injector
    monkeypatch.setattr(memory_injector, "get_active_project", lambda: "活跃项目X")
    orch.delegate("executor", "干活")
    assert fake.last_project == "活跃项目X"


def test_delegate_child_inherits_parent_project(monkeypatch):
    """子员工内部再 delegate 时，沿派活链继承父级项目。"""
    fake = _FakeAgent()
    monkeypatch.setattr(orch, "_get_subagent", lambda role, project=None: fake)
    # 模拟"已在某子员工线程里，ctx 带着父级项目"
    orch._local.ctx = {"shared": {"count": 0, "max": 16,
                                  "lock": __import__("threading").Lock()},
                       "depth": 0, "project": "父项目"}
    orch.delegate("executor", "继续干")
    assert fake.last_project == "父项目"


def test_executor_has_restricted_delegate():
    """executor 挂了受限 delegate，且 enum 不含 writer（不能派写手）。"""
    from executor_worker import ExecutorWorker
    w = ExecutorWorker()
    tool_names = {d["function"]["name"] for d in w.tool_defs}
    assert "delegate" in tool_names
    deleg = next(d for d in w.tool_defs if d["function"]["name"] == "delegate")
    enum = set(deleg["function"]["parameters"]["properties"]["role"]["enum"])
    assert "writer" not in enum and "executor" in enum
