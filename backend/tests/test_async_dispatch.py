#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_async_dispatch.py — M11 内核1 回归哨兵：工具分发异步化的向后兼容保证。

内核 1 把 AgentBase._execute_tool 改成 async，加 iscoroutine 守卫，
让同一个单一咽喉既能跑现有 13 个同步工具，又能 await 新的异步工具（MCP）。

本文件锁定的不变量（任何后续改动都不许破坏）：
  1. 同步工具（返回 dict）走 async 路径，结果与旧行为完全一致。
  2. 异步工具（协程）被正确 await，拿到其返回值。
  3. 未知工具 → {"error": 未知工具…}。
  4. PermissionRequest 必须向上传播（同步和异步两条路径都要），
     由 ws 层捕获推权限卡片——绝不能被吞成 error dict。
  5. 参数不匹配（TypeError）→ {"error": 工具参数错误…}。
  6. 其它异常（同步/异步两条路径）→ {"error": 工具执行异常…}。

不触网、不调真模型：用最小 dispatch 直接验咽喉行为。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_async_dispatch.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import agent_base as ab  # noqa: E402


def _mk_agent(dispatch: dict) -> ab.AgentBase:
    return ab.AgentBase(
        name="t", api_key="", model="m", base_url="u",
        system_prompt="", tool_defs=[], tool_dispatch=dispatch,
    )


# ── 1. 同步工具：走 async 路径，行为不变（向后兼容的核心保证）──
def test_sync_tool_unchanged():
    a = _mk_agent({"echo": lambda **kw: {"ok": True, "got": kw}})
    r = asyncio.run(a._execute_tool("echo", {"x": 1}))
    assert r == {"ok": True, "got": {"x": 1}}


# ── 2. 异步工具：被正确 await ──
def test_async_tool_awaited():
    async def _aecho(**kw):
        await asyncio.sleep(0)
        return {"ok": True, "is_async": True, "got": kw}
    a = _mk_agent({"aecho": _aecho})
    r = asyncio.run(a._execute_tool("aecho", {"y": 2}))
    assert r == {"ok": True, "is_async": True, "got": {"y": 2}}


# ── 3. 未知工具 ──
def test_unknown_tool():
    a = _mk_agent({})
    r = asyncio.run(a._execute_tool("nope", {}))
    assert "error" in r and "未知工具" in r["error"]


# ── 4. PermissionRequest 向上传播（同步路径）──
def test_permission_request_propagates_sync():
    def _need(**kw):
        raise ab.PermissionRequest(api_name="搜索 API", reason="需要配置搜索服务")
    a = _mk_agent({"need": _need})
    with pytest.raises(ab.PermissionRequest):
        asyncio.run(a._execute_tool("need", {}))


# ── 4b. PermissionRequest 向上传播（异步路径，await 中抛出）──
def test_permission_request_propagates_async():
    async def _need(**kw):
        await asyncio.sleep(0)
        raise ab.PermissionRequest(api_name="MCP 服务", reason="未连接")
    a = _mk_agent({"need": _need})
    with pytest.raises(ab.PermissionRequest):
        asyncio.run(a._execute_tool("need", {}))


# ── 5. 参数不匹配 → error dict ──
def test_type_error_becomes_error_dict():
    def _needs_x(x):
        return {"x": x}
    a = _mk_agent({"strict": _needs_x})
    r = asyncio.run(a._execute_tool("strict", {"wrong": 1}))
    assert "error" in r and "参数" in r["error"]


# ── 6. 同步工具内部异常 → error dict ──
def test_sync_exception_becomes_error_dict():
    def _raise(**kw):
        raise RuntimeError("同步炸了")
    a = _mk_agent({"bad": _raise})
    r = asyncio.run(a._execute_tool("bad", {}))
    assert "error" in r and "异常" in r["error"] and "同步炸了" in r["error"]


# ── 6b. 异步工具 await 中异常 → error dict ──
def test_async_exception_becomes_error_dict():
    async def _raise(**kw):
        await asyncio.sleep(0)
        raise RuntimeError("异步炸了")
    a = _mk_agent({"bad": _raise})
    r = asyncio.run(a._execute_tool("bad", {}))
    assert "error" in r and "异常" in r["error"] and "异步炸了" in r["error"]
