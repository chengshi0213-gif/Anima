#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_hooks.py — M14 内核3 工具钩子单测。

锁定的不变量：
  · 默认无钩子 → run_pre_tool 返回 None（零行为变化）。
  · pre_tool 钩子返回 {"block": ...} → run_pre_tool 返回 veto dict（否决工具）。
  · match 过滤：工具名不匹配 → 钩子不触发。
  · async 钩子也能 await。
  · 坏钩子（抛异常）被吞掉，不影响主流程。
  · post_tool 钩子被调用、能读到 result。
  · shell 钩子：JSON payload 喂 stdin，返回退出码。

运行: cd backend && python -m pytest tests/test_hooks.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
_TESTS = Path(__file__).parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_TESTS))      # 让 _hook_fixtures 可 import

import hooks as hk  # noqa: E402
import _hook_fixtures as fx  # noqa: E402


def _set_hooks(monkeypatch, cfg: dict):
    import config
    monkeypatch.setattr(config, "_get",
                        lambda k, d=None: cfg if k == "security.hooks" else d,
                        raising=False)


@pytest.fixture(autouse=True)
def _clear_record():
    fx.RECORD.clear()
    yield
    fx.RECORD.clear()


CTX = {"session_id": "s", "agent": "xi"}


# ── 默认无钩子 ──
def test_no_hooks_returns_none(monkeypatch):
    _set_hooks(monkeypatch, {})
    assert asyncio.run(hk.run_pre_tool("file_write", {"path": "a"}, CTX)) is None


# ── pre_tool veto ──
def test_pre_tool_block(monkeypatch):
    _set_hooks(monkeypatch, {"pre_tool": [{"python": "_hook_fixtures:block_hook"}]})
    out = asyncio.run(hk.run_pre_tool("file_write", {"path": "a"}, CTX))
    assert out and out.get("blocked") and "敏感路径" in out["error"]


def test_pre_tool_async_block(monkeypatch):
    _set_hooks(monkeypatch, {"pre_tool": [{"python": "_hook_fixtures:async_block_hook"}]})
    out = asyncio.run(hk.run_pre_tool("shell_run", {}, CTX))
    assert out and out.get("blocked")


# ── match 过滤 ──
def test_match_filter_skips_nonmatching(monkeypatch):
    _set_hooks(monkeypatch, {"pre_tool": [
        {"match": "file_write", "python": "_hook_fixtures:block_hook"}]})
    # 工具是 shell_run，不匹配 file_write → 钩子不触发 → 放行
    assert asyncio.run(hk.run_pre_tool("shell_run", {}, CTX)) is None
    # 工具匹配 → 触发拦截
    assert asyncio.run(hk.run_pre_tool("file_write", {}, CTX)) is not None


# ── 坏钩子被吞 ──
def test_bad_hook_swallowed(monkeypatch):
    _set_hooks(monkeypatch, {"pre_tool": [{"python": "_hook_fixtures:boom_hook"}]})
    assert asyncio.run(hk.run_pre_tool("file_write", {}, CTX)) is None


# ── post_tool ──
def test_post_tool_runs_and_sees_result(monkeypatch):
    _set_hooks(monkeypatch, {"post_tool": [{"python": "_hook_fixtures:record_post"}]})
    asyncio.run(hk.run_post_tool("file_write", {"path": "a"}, {"bytes": 10}, CTX))
    assert fx.RECORD == [("post", "file_write", {"bytes": 10})]


# ── shell 钩子 ──
def test_shell_hook_runs(monkeypatch):
    # 跨平台：用当前解释器跑一个秒退的命令，验证退出码与 stdin 喂入不报错
    cmd = f'"{sys.executable}" -c "import sys,json; sys.stdin.read(); sys.exit(0)"'
    _set_hooks(monkeypatch, {"post_tool": [{"shell": cmd}]})
    # 不抛即通过（post_tool 吞掉一切）；顺带直接验 _call_shell 返回码
    asyncio.run(hk.run_post_tool("file_write", {"path": "a"}, {"ok": True}, CTX))
    out = asyncio.run(hk._call_shell(cmd, {"x": 1}))
    assert out["exit_code"] == 0
