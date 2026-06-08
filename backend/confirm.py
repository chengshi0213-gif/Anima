#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
confirm.py — M14 内核3：危险操作确认（ConfirmBroker）。

挂在 _execute_tool 唯一咽喉前：危险工具 → 发 confirm_request 事件 + 建 asyncio.Future
→ 用户用 confirm_response action 解 Future → 放行 / 中止。复用内核1 异步 + 内核2 WS 往返。

【安全默认：全关】策略默认 off（=不确认，直接放行）。只有用户在 config 的
security.confirm 里显式开了某类别才生效——保证前端确认 UI 落地前，现有
shell / 文件编辑行为零改动。这是"机制先就位、默认不打扰"的 opt-in 设计。

策略值：off（放行，默认）/ ask（问用户）/ allow（永远放行）/ deny（永远拒）。
无人值守（子员工 / scheduler / 无活 ws）：ask 类别按 security.confirm.unattended
决定（默认拒），不卡死。
"""
from __future__ import annotations

import asyncio
import uuid

# 默认全 off：前端确认 UI 落地前，机制在位但不打扰。
_DEFAULT_POLICY = {
    "shell": "off",
    "write_outside_workspace": "off",
    "git_push": "off",
    "mcp_destructive": "off",
}

_RISK = {
    "shell": "high",
    "write_outside_workspace": "medium",
    "git_push": "high",
    "mcp_destructive": "high",
}

_DESTRUCTIVE_KW = ("delete", "remove", "drop", "destroy", "purge", "truncate")

_ASK_TIMEOUT = 300  # 秒；用户 5 分钟不点 = 当作拒绝（安全侧）


def _policy() -> dict:
    try:
        from config import _get
        p = _get("security.confirm", {}) or {}
    except Exception:
        p = {}
    return {**_DEFAULT_POLICY, **p}


def _outside_workspace(path: str) -> bool:
    try:
        from pathlib import Path
        from config import WORKSPACE_DIR
        p = Path(path).expanduser().resolve()
        ws = Path(WORKSPACE_DIR).resolve()
        return p != ws and ws not in p.parents
    except Exception:
        return False


def classify(name: str, args: dict) -> str | None:
    """把一次工具调用归到确认类别；安全/无需确认则 None。"""
    if name == "shell_run":
        return "shell"
    if name in ("file_write", "file_edit"):
        return "write_outside_workspace" if _outside_workspace(str(args.get("path", ""))) else None
    if name.startswith("mcp__"):
        low = name.lower()
        return "mcp_destructive" if any(k in low for k in _DESTRUCTIVE_KW) else None
    if name == "git_push":
        return "git_push"
    return None


def _detail(name: str, args: dict) -> str:
    if name == "shell_run":
        return str(args.get("command", ""))[:200]
    if name in ("file_write", "file_edit"):
        return str(args.get("path", ""))[:200]
    return ", ".join(f"{k}={str(v)[:40]}" for k, v in args.items())[:200]


class ConfirmBroker:
    """确认中枢：发起请求 + 等用户答复 + 记住"本次会话/永久允许"。"""

    def __init__(self):
        self._pending: dict[str, asyncio.Future] = {}
        self._session_allow: dict[str, set] = {}   # session_id -> {kind}
        self._always_allow: set = set()            # 本进程"永久允许"的 kind

    async def guard(self, kind: str, name: str, args: dict, ctx: dict) -> bool:
        """返回 True=放行，False=拒绝。咽喉里只在 classify 命中时调用。"""
        mode = _policy().get(kind, "off")
        if mode in ("off", "allow"):
            return True
        if mode == "deny":
            return False
        # mode == "ask"
        if kind in self._always_allow:
            return True
        sid = ctx.get("session_id")
        if sid and kind in self._session_allow.get(sid, set()):
            return True
        ws = ctx.get("ws")
        if ws is None:
            # 无人值守：默认拒，可用 security.confirm.unattended=allow 放开
            return _policy().get("unattended") == "allow"
        return await self._ask(ws, kind, name, args, ctx)

    async def _ask(self, ws, kind: str, name: str, args: dict, ctx: dict) -> bool:
        confirm_id = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self._pending[confirm_id] = fut
        try:
            await ws.send_json({"type": "confirm_request", "data": {
                "confirm_id": confirm_id, "kind": kind, "tool": name,
                "detail": _detail(name, args), "risk": _RISK.get(kind, "medium"),
            }})
        except Exception:
            self._pending.pop(confirm_id, None)
            return False
        try:
            approved, scope = await asyncio.wait_for(fut, timeout=_ASK_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return False
        finally:
            self._pending.pop(confirm_id, None)
        if approved:
            self._remember(kind, scope, ctx.get("session_id"))
        return approved

    def _remember(self, kind: str, scope: str, sid: str | None):
        if scope == "session" and sid:
            self._session_allow.setdefault(sid, set()).add(kind)
        elif scope == "always":
            self._always_allow.add(kind)

    def resolve(self, confirm_id: str, approved: bool, scope: str = "once") -> bool:
        """用户答复 confirm_response → 解开对应 Future。返回是否命中一个等待中的请求。"""
        fut = self._pending.get(confirm_id)
        if fut is not None and not fut.done():
            fut.set_result((bool(approved), scope))
            return True
        return False

    def _reset(self):
        self._pending.clear()
        self._session_allow.clear()
        self._always_allow.clear()


_BROKER: ConfirmBroker | None = None


def get_broker() -> ConfirmBroker:
    global _BROKER
    if _BROKER is None:
        _BROKER = ConfirmBroker()
    return _BROKER
