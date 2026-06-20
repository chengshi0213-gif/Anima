#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_mcp_client.py — M11 MCP 客户端单元测试。

不依赖真实 MCP server，也不依赖官方 mcp SDK：用 fake session / fake result
直接验证纯逻辑与桥接行为。锁定的不变量：
  · _content_to_dict：text blocks 合并 / isError→error / structured 透传。
  · 命名空间隔离 mcp__<server>__<tool>：两个 server 同名工具不互撞。
  · snapshot：tool_defs 形状正确、dispatch 闭包绑定到正确的 server/tool。
  · acall：未连接 server→error；调用异常→error；正常→content dict。
  · call_threadsafe：未 boot→error dict（不抛）；主循环上→返回协程；
    子线程上→marshal 回主循环阻塞拿结果。
  · _resolve_env：${api.x}（读 config）/ ${ENV}（读环境变量）/ 字面值。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_mcp_client.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import threading
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import mcp_client as mc  # noqa: E402
from mcp_client import MCPManager  # noqa: E402


# ── fake MCP 协议对象 ──
class _Block:
    def __init__(self, text=None, type="text"):
        self.text = text
        self.type = type


class _Result:
    def __init__(self, content, isError=False, structuredContent=None):
        self.content = content
        self.isError = isError
        self.structuredContent = structuredContent


class _FakeSession:
    """记录收到的调用，按 responder 返回结果。"""
    def __init__(self, responder):
        self._responder = responder
        self.calls = []

    async def call_tool(self, tool, args):
        self.calls.append((tool, args))
        return self._responder(tool, args)


@pytest.fixture(autouse=True)
def _reset_manager():
    MCPManager._reset()
    yield
    MCPManager._reset()


# ── _content_to_dict ──
def test_content_to_dict_text():
    r = _Result([_Block(text="hello"), _Block(text="world")])
    assert mc._content_to_dict(r) == {"text": "hello\nworld"}


def test_content_to_dict_error():
    r = _Result([_Block(text="boom")], isError=True)
    out = mc._content_to_dict(r)
    assert "error" in out and "boom" in out["error"]


def test_content_to_dict_structured():
    r = _Result([_Block(text="ok")], structuredContent={"n": 1})
    out = mc._content_to_dict(r)
    assert out["text"] == "ok" and out["structured"] == {"n": 1}


def test_content_to_dict_nontext_block():
    r = _Result([_Block(text=None, type="image")])
    assert "[image 内容]" in mc._content_to_dict(r)["text"]


# ── _compose_mcp_fragment ──
def test_fragment_empty_when_no_tools():
    assert mc._compose_mcp_fragment({}) == ""
    assert mc._compose_mcp_fragment({"a": []}) == ""


def test_fragment_lists_namespaced_tools():
    frag = mc._compose_mcp_fragment({"github": [{"name": "create_issue"}]})
    assert "mcp__github__create_issue" in frag and "MCP" in frag


# ── snapshot：命名空间隔离 + 闭包绑定 ──
def test_snapshot_namespacing():
    MCPManager._tools = {
        "github": [{"name": "search", "description": "gh", "inputSchema": {"type": "object"}}],
        "notion": [{"name": "search", "description": "no", "inputSchema": None}],
    }
    snap = MCPManager.snapshot()
    names = {d["function"]["name"] for d in snap.tool_defs}
    assert names == {"mcp__github__search", "mcp__notion__search"}
    # inputSchema=None 时回退到空 object schema（合法 JSON Schema）
    no = next(d for d in snap.tool_defs if d["function"]["name"] == "mcp__notion__search")
    assert no["function"]["parameters"] == {"type": "object", "properties": {}}
    assert set(snap.dispatch) == {"mcp__github__search", "mcp__notion__search"}


def test_snapshot_dispatch_routes_to_correct_server():
    """两个 server 同名工具：dispatch 闭包必须各自路由到正确 server（防晚绑定）。"""
    seen = {}
    sess_a = _FakeSession(lambda t, a: _Result([_Block(text="A")]))
    sess_b = _FakeSession(lambda t, a: _Result([_Block(text="B")]))
    MCPManager._tools = {"a": [{"name": "go"}], "b": [{"name": "go"}]}
    MCPManager._sessions = {"a": sess_a, "b": sess_b}

    # 在子线程视角调用：起一个真实主循环承载 acall
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    MCPManager.main_loop = loop
    try:
        snap = MCPManager.snapshot()
        ra = snap.dispatch["mcp__a__go"](x=1)
        rb = snap.dispatch["mcp__b__go"](y=2)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2)
    assert ra == {"text": "A"} and rb == {"text": "B"}
    assert sess_a.calls == [("go", {"x": 1})]
    assert sess_b.calls == [("go", {"y": 2})]


# ── acall ──
def test_acall_unconnected_server():
    out = asyncio.run(MCPManager.acall("ghost", "x", {}))
    assert "error" in out and "未连接" in out["error"]


def test_acall_success_and_exception():
    MCPManager._sessions = {
        "ok": _FakeSession(lambda t, a: _Result([_Block(text="done")])),
        "bad": _FakeSession(lambda t, a: (_ for _ in ()).throw(RuntimeError("挂了"))),
    }
    assert asyncio.run(MCPManager.acall("ok", "t", {})) == {"text": "done"}
    err = asyncio.run(MCPManager.acall("bad", "t", {}))
    assert "error" in err and "挂了" in err["error"]


# ── call_threadsafe ──
def test_call_threadsafe_not_booted():
    # main_loop=None（未 boot）→ 返回 error dict，不抛、不留未 await 协程
    out = MCPManager.call_threadsafe("a", "go", {})
    assert isinstance(out, dict) and "error" in out and "未就绪" in out["error"]


def test_call_threadsafe_on_main_loop_returns_coroutine():
    async def _inner():
        MCPManager.main_loop = asyncio.get_running_loop()
        MCPManager._sessions = {"a": _FakeSession(lambda t, a: _Result([_Block(text="hi")]))}
        ret = MCPManager.call_threadsafe("a", "go", {})
        assert inspect.iscoroutine(ret)          # 主循环上→交给异步 _execute_tool await
        assert await ret == {"text": "hi"}
    asyncio.run(_inner())


# ── _resolve_env ──
def test_resolve_env_literal_and_config_and_envvar(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "from-env")
    import config
    monkeypatch.setattr(config, "_get", lambda k, d="": "from-config" if k == "api.github_token" else d, raising=False)
    out = mc._resolve_env({
        "LIT": "plain",
        "CFG": "${api.github_token}",
        "ENV": "${MY_TOKEN}",
    })
    assert out == {"LIT": "plain", "CFG": "from-config", "ENV": "from-env"}


def test_resolve_env_none():
    assert mc._resolve_env(None) is None
    assert mc._resolve_env({}) is None


# ── _load_mcp_config ──
def test_load_mcp_config(monkeypatch):
    import config
    monkeypatch.setattr(config, "_get",
                        lambda k, d=None: [{"name": "x", "enabled": True}] if k == "mcp.servers" else d,
                        raising=False)
    servers = mc._load_mcp_config()
    assert servers == [{"name": "x", "enabled": True}]


def test_load_mcp_config_absent(monkeypatch):
    import config
    monkeypatch.setattr(config, "_get", lambda k, d=None: d, raising=False)
    assert mc._load_mcp_config() == []
