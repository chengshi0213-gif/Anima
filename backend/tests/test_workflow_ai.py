#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_workflow_ai.py — AI 结构化搭建工作流（M10 Part 1）单元测试

不触网、不调真模型：用一个 _FakeGen 假 generator，其 `_call_api` 直接
吐预设好的内容。验证：
  - 鲁棒解析：剥 ```json``` 围栏 / 前后废话 / 整段坏 JSON 不致命。
  - 全节点类型规整：sequential / parallel / condition / loop。
  - 非法 agent → 纠正成 xi 并告警；空 prompt 告警。
  - {{变量}} 探测保序去重。
  - 对话式编辑：传 current_steps 时把它塞进 system 提示。
  - 错误路径：空目标 / 模型报错 / 不可解析 JSON / 解析不出步骤。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_workflow_ai.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import workflow_ai as wa  # noqa: E402


class _FakeGen:
    """假 generator：记录收到的 messages，按预设吐内容/错误。"""

    def __init__(self, content="", error=None):
        self._content = content
        self._error = error
        self.last_messages = None
        self.call_count = 0

    async def _call_api(self, messages, tools=None, stream=False):
        self.call_count += 1
        self.last_messages = messages
        # 断言调用方没误开 ReAct（纯生成必须 tools=None）
        assert tools is None
        assert stream is False
        if self._error is not None:
            return {"error": self._error}
        return {"content": self._content}


def _run(coro):
    import asyncio
    return asyncio.run(coro)


# ── 解析鲁棒性 ──────────────────────────────────────────────────────────────

def test_strips_json_fence():
    payload = {"name": "调研流", "steps": [
        {"type": "sequential", "agent": "xi", "prompt": "查 {{主题}}"}
    ], "explanation": "先查后写"}
    gen = _FakeGen(content="这是结果：\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```\n搞定")
    out = _run(wa.ai_build_workflow(gen, "调研一个主题"))
    assert out["ok"] is True
    assert out["name"] == "调研流"
    assert out["steps"][0]["agent"] == "xi"
    assert out["variables"] == ["主题"]


def test_extracts_bare_object_with_garbage_around():
    payload = {"steps": [{"agent": "writer", "prompt": "写稿"}]}
    gen = _FakeGen(content="好的我帮你编排 " + json.dumps(payload, ensure_ascii=False) + " 以上。")
    out = _run(wa.ai_build_workflow(gen, "写点东西"))
    assert out["ok"] is True
    assert out["steps"][0]["type"] == "sequential"
    assert out["steps"][0]["agent"] == "writer"


def test_top_level_list_is_accepted_as_steps():
    payload = [{"agent": "xi", "prompt": "随便聊聊"}]
    gen = _FakeGen(content=json.dumps(payload, ensure_ascii=False))
    out = _run(wa.ai_build_workflow(gen, "闲聊"))
    assert out["ok"] is True
    assert len(out["steps"]) == 1
    assert out["name"] == "AI 工作流"  # 列表没名字 → 默认名


def test_unparseable_json_is_not_fatal():
    gen = _FakeGen(content="完全不是 JSON 的一段话")
    out = _run(wa.ai_build_workflow(gen, "随便"))
    assert out["ok"] is False
    assert "raw" in out


# ── 全节点类型 ──────────────────────────────────────────────────────────────

def test_all_node_types_normalized():
    payload = {"name": "复合流", "steps": [
        {"type": "sequential", "agent": "researcher", "prompt": "查 {{产品}}"},
        {"type": "parallel", "branches": [
            {"agent": "writer", "prompt": "写卖点"},
            {"agent": "analyst", "prompt": "算数据"},
        ]},
        {"type": "condition", "keyword": "通过",
         "true_step": {"agent": "writer", "prompt": "定稿"},
         "false_step": {"agent": "critic", "prompt": "退回重写"}},
        {"type": "loop", "max_iter": 5, "stop_keyword": "完成",
         "step": {"agent": "executor", "prompt": "迭代实现"}},
    ]}
    gen = _FakeGen(content=json.dumps(payload, ensure_ascii=False))
    out = _run(wa.ai_build_workflow(gen, "做个产品页"))
    assert out["ok"] is True
    types = [s["type"] for s in out["steps"]]
    assert types == ["sequential", "parallel", "condition", "loop"]
    par = out["steps"][1]
    assert len(par["branches"]) == 2
    cond = out["steps"][2]
    assert cond["true_step"]["agent"] == "writer"
    assert cond["false_step"]["agent"] == "critic"
    lp = out["steps"][3]
    assert lp["max_iter"] == 5 and lp["stop_keyword"] == "完成"
    assert lp["step"]["agent"] == "executor"


def test_unknown_node_type_falls_back_to_sequential():
    payload = {"steps": [{"type": "magic", "agent": "xi", "prompt": "?"}]}
    gen = _FakeGen(content=json.dumps(payload, ensure_ascii=False))
    out = _run(wa.ai_build_workflow(gen, "x"))
    assert out["ok"] is True
    assert out["steps"][0]["type"] == "sequential"
    assert any("未知节点类型" in w for w in out["warnings"])


# ── 校验：非法 agent / 空 prompt ─────────────────────────────────────────────

def test_unknown_agent_corrected_to_xi():
    payload = {"steps": [{"agent": "nonexistent", "prompt": "干活"}]}
    gen = _FakeGen(content=json.dumps(payload, ensure_ascii=False))
    out = _run(wa.ai_build_workflow(gen, "x"))
    assert out["steps"][0]["agent"] == "xi"
    assert any("未知 agent" in w for w in out["warnings"])


def test_empty_prompt_warns():
    payload = {"steps": [{"agent": "writer", "prompt": "   "}]}
    gen = _FakeGen(content=json.dumps(payload, ensure_ascii=False))
    out = _run(wa.ai_build_workflow(gen, "x"))
    assert any("prompt 为空" in w for w in out["warnings"])


def test_empty_parallel_branches_skipped():
    payload = {"steps": [
        {"type": "parallel", "branches": []},
        {"agent": "xi", "prompt": "兜底"},
    ]}
    gen = _FakeGen(content=json.dumps(payload, ensure_ascii=False))
    out = _run(wa.ai_build_workflow(gen, "x"))
    # 空并行被跳过，只剩兜底那步
    assert len(out["steps"]) == 1
    assert out["steps"][0]["agent"] == "xi"
    assert any("并行节点无有效分支" in w for w in out["warnings"])


# ── 变量探测 ────────────────────────────────────────────────────────────────

def test_detect_variables_ordered_dedup():
    steps = [
        {"type": "sequential", "prompt": "查 {{主题}} 和 {{受众}}"},
        {"type": "parallel", "branches": [
            {"prompt": "写 {{主题}}"}, {"prompt": "配图 {{风格}}"},
        ]},
    ]
    assert wa.detect_variables(steps) == ["主题", "受众", "风格"]


# ── 对话式编辑 ──────────────────────────────────────────────────────────────

def test_edit_mode_injects_current_steps():
    current = [{"type": "sequential", "agent": "writer", "prompt": "旧步骤"}]
    payload = {"steps": [{"agent": "writer", "prompt": "新步骤"}]}
    gen = _FakeGen(content=json.dumps(payload, ensure_ascii=False))
    out = _run(wa.ai_build_workflow(gen, "把第一步改一下", current_steps=current))
    assert out["ok"] is True
    sys_msg = gen.last_messages[0]["content"]
    assert "修改请求" in sys_msg
    assert "旧步骤" in sys_msg  # 当前 steps 被塞进提示


# ── 错误路径 ────────────────────────────────────────────────────────────────

def test_empty_description_rejected():
    gen = _FakeGen(content="{}")
    out = _run(wa.ai_build_workflow(gen, "   "))
    assert out["ok"] is False
    assert gen.call_count == 0  # 根本不该调模型


def test_model_error_propagated():
    gen = _FakeGen(error="rate limited")
    out = _run(wa.ai_build_workflow(gen, "做点啥"))
    assert out["ok"] is False
    assert "rate limited" in out["error"]


def test_no_steps_produced_is_error():
    payload = {"name": "空流", "steps": []}
    gen = _FakeGen(content=json.dumps(payload, ensure_ascii=False))
    out = _run(wa.ai_build_workflow(gen, "x"))
    assert out["ok"] is False
    assert "有效步骤" in out["error"]


# ── 路由层 /workflow/ai_build ───────────────────────────────────────────────

class _FakeReq:
    """极简假 aiohttp 请求：只实现 handler 用到的 .json() 与 .app。"""

    def __init__(self, body, app):
        self._body = body
        self.app = app
        self.match_info = {}

    async def json(self):
        if self._body is _BAD:
            raise ValueError("invalid json")
        return self._body


_BAD = object()


class _FakeSrv:
    def __init__(self, worker):
        self.worker = worker


def _call_route(body, servers):
    from routes.workflow import workflow_ai_build_handler
    app = {"servers": servers}
    return _run(workflow_ai_build_handler(_FakeReq(body, app)))


def test_route_happy_path():
    payload = {"name": "调研流", "steps": [
        {"agent": "researcher", "prompt": "查 {{主题}}"}]}
    gen = _FakeGen(content=json.dumps(payload, ensure_ascii=False))
    resp = _call_route({"description": "调研一个主题"},
                       {"tianyuan": _FakeSrv(gen)})
    assert resp.status == 200
    data = json.loads(resp.text)
    assert data["ok"] is True
    assert data["variables"] == ["主题"]


def test_route_empty_description_400():
    gen = _FakeGen(content="{}")
    resp = _call_route({"description": "   "}, {"tianyuan": _FakeSrv(gen)})
    assert resp.status == 400
    assert gen.call_count == 0


def test_route_falls_back_to_xi_when_no_tianyuan():
    payload = {"steps": [{"agent": "xi", "prompt": "聊聊"}]}
    gen = _FakeGen(content=json.dumps(payload, ensure_ascii=False))
    resp = _call_route({"description": "闲聊"}, {"xi": _FakeSrv(gen)})
    assert resp.status == 200
    assert gen.call_count == 1


def test_route_no_planner_available_503():
    resp = _call_route({"description": "做点啥"}, {})
    assert resp.status == 503


def test_route_unbuildable_returns_422():
    gen = _FakeGen(content="不是 JSON")
    resp = _call_route({"description": "做点啥"}, {"tianyuan": _FakeSrv(gen)})
    assert resp.status == 422
    assert json.loads(resp.text)["ok"] is False
