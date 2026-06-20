#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_confirm.py — M14 内核3 确认中枢单测。

锁定的不变量：
  · 默认策略全 off → guard 一律放行（前端 UI 落地前零打扰）。
  · classify：shell_run→shell；file_write 出 workspace→write_outside_workspace，
    在内→None；mcp 破坏性→mcp_destructive，非破坏→None；git_push→git_push。
  · guard 策略：off/allow→True，deny→False，ask→走问询。
  · ask + 会话允许 / 永久允许 → 免再问。
  · 无人值守（ws=None）+ ask → 默认拒；unattended=allow → 放行。
  · ask + 有 ws → 发 confirm_request；resolve(True/False) 解 Future；
    scope=session/always 记住后续免问。
  · resolve 未知 id → False。

运行: cd backend && python -m pytest tests/test_confirm.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import confirm as cf  # noqa: E402
from confirm import ConfirmBroker, classify  # noqa: E402


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload):
        self.sent.append(payload)


def _set_policy(monkeypatch, policy: dict):
    import config
    monkeypatch.setattr(config, "_get",
                        lambda k, d=None: policy if k == "security.confirm" else d,
                        raising=False)


def _set_workspace(monkeypatch, path):
    import config
    monkeypatch.setattr(config, "WORKSPACE_DIR", Path(path), raising=False)


# ── classify ──
def test_classify_shell():
    assert classify("shell_run", {"command": "ls"}) == "shell"


def test_classify_file_inside_vs_outside(monkeypatch, tmp_path):
    _set_workspace(monkeypatch, tmp_path)
    inside = str(tmp_path / "a.py")
    outside = str(tmp_path.parent / "other" / "b.py")
    assert classify("file_write", {"path": inside}) is None
    assert classify("file_edit", {"path": outside}) == "write_outside_workspace"


def test_classify_mcp_destructive_vs_safe():
    assert classify("mcp__gh__delete_repo", {}) == "mcp_destructive"
    assert classify("mcp__gh__search", {}) is None


def test_classify_git_push_and_unknown():
    assert classify("git_push", {}) == "git_push"
    assert classify("file_read", {"path": "x"}) is None


# ── 默认全 off：零打扰 ──
def test_default_policy_allows_everything(monkeypatch):
    _set_policy(monkeypatch, {})   # 用户没配 → 默认全 off
    b = ConfirmBroker()
    ctx = {"ws": _FakeWS(), "session_id": "s", "agent": "xi"}
    assert asyncio.run(b.guard("shell", "shell_run", {"command": "ls"}, ctx)) is True


# ── 策略分支 ──
def test_guard_deny(monkeypatch):
    _set_policy(monkeypatch, {"shell": "deny"})
    b = ConfirmBroker()
    ctx = {"ws": _FakeWS(), "session_id": "s"}
    assert asyncio.run(b.guard("shell", "shell_run", {"command": "x"}, ctx)) is False


def test_guard_allow(monkeypatch):
    _set_policy(monkeypatch, {"shell": "allow"})
    b = ConfirmBroker()
    assert asyncio.run(b.guard("shell", "shell_run", {}, {"ws": None})) is True


def test_guard_unattended_ask_denies(monkeypatch):
    _set_policy(monkeypatch, {"shell": "ask"})
    b = ConfirmBroker()
    assert asyncio.run(b.guard("shell", "shell_run", {}, {"ws": None, "session_id": "s"})) is False


def test_guard_unattended_allow_opt_in(monkeypatch):
    _set_policy(monkeypatch, {"shell": "ask", "unattended": "allow"})
    b = ConfirmBroker()
    assert asyncio.run(b.guard("shell", "shell_run", {}, {"ws": None, "session_id": "s"})) is True


# ── ask 往返 ──
def test_guard_ask_approved_and_session_remembered(monkeypatch):
    _set_policy(monkeypatch, {"shell": "ask"})

    async def scenario():
        b = ConfirmBroker()
        ws = _FakeWS()
        ctx = {"ws": ws, "session_id": "s1", "agent": "xi"}
        task = asyncio.create_task(b.guard("shell", "shell_run", {"command": "ls"}, ctx))
        await asyncio.sleep(0.01)                       # 让 _ask 把请求发出去
        assert ws.sent and ws.sent[0]["type"] == "confirm_request"
        cid = ws.sent[0]["data"]["confirm_id"]
        assert b.resolve(cid, True, "session") is True
        assert await task is True
        # 同会话同类别：免再问，直接放行（不再发新请求）
        again = await b.guard("shell", "shell_run", {"command": "pwd"}, ctx)
        assert again is True and len(ws.sent) == 1

    asyncio.run(scenario())


def test_guard_ask_denied(monkeypatch):
    _set_policy(monkeypatch, {"shell": "ask"})

    async def scenario():
        b = ConfirmBroker()
        ws = _FakeWS()
        ctx = {"ws": ws, "session_id": "s2"}
        task = asyncio.create_task(b.guard("shell", "shell_run", {"command": "rm"}, ctx))
        await asyncio.sleep(0.01)
        cid = ws.sent[0]["data"]["confirm_id"]
        b.resolve(cid, False)
        assert await task is False

    asyncio.run(scenario())


def test_guard_ask_always_remembered_across_sessions(monkeypatch):
    _set_policy(monkeypatch, {"shell": "ask"})

    async def scenario():
        b = ConfirmBroker()
        ws = _FakeWS()
        task = asyncio.create_task(
            b.guard("shell", "shell_run", {}, {"ws": ws, "session_id": "sA"}))
        await asyncio.sleep(0.01)
        b.resolve(ws.sent[0]["data"]["confirm_id"], True, "always")
        assert await task is True
        # 不同会话也免问
        ws2 = _FakeWS()
        ok = await b.guard("shell", "shell_run", {}, {"ws": ws2, "session_id": "sB"})
        assert ok is True and ws2.sent == []

    asyncio.run(scenario())


def test_resolve_unknown_id():
    b = ConfirmBroker()
    assert b.resolve("nope", True) is False
