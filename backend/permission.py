#!/usr/bin/env python3
"""permission.py — D3: 权限分级（readonly/confirm/acceptEdits/auto）+ 自定义规则。

在 agent_base._pre_tool 中调用 check_tool_permission，决定放行/确认/拒绝。
依托已有 M14 confirm 闸门——"confirm" 结果交给 ConfirmBroker.guard 走 WS 确认流。
"""
from __future__ import annotations

import re
from fnmatch import fnmatch

_WRITE_TOOLS = frozenset({
    "file_write", "file_edit", "shell_run", "apply_patch",
    "git_commit", "git_create_branch", "git_push",
    "install_pkg", "checkpoint", "rollback",
})

_EDIT_TOOLS = frozenset({"file_write", "file_edit", "apply_patch"})

_ALWAYS_CONFIRM = frozenset({"git_push", "create_pr"})


def _get_mode() -> str:
    try:
        from config import _get
        return _get("coding.permission_mode", "auto") or "auto"
    except Exception:
        return "auto"


def _get_rules() -> list[dict]:
    try:
        from config import _get
        return _get("coding.rules", []) or []
    except Exception:
        return []


def check_tool_permission(name: str, args: dict) -> str | None:
    """返回 None=放行, "deny:reason"=拒绝, "confirm"=需确认。

    1. 先查自定义规则（deny/confirm 优先级最高）
    2. 再按 permission_mode 决定
    """
    if name in _ALWAYS_CONFIRM:
        return "confirm"

    for rule in _get_rules():
        if rule.get("tool") != name:
            continue
        pattern = rule.get("pattern", "")
        path_glob = rule.get("path", "")
        action = rule.get("action", "confirm")
        if pattern and _match_pattern(args, pattern):
            if action == "deny":
                return f"deny:规则拒绝 {name} (pattern: {pattern})"
            if action == "confirm":
                return "confirm"
        if path_glob and _match_path(args, path_glob):
            if action == "deny":
                return f"deny:规则拒绝 {name} (path: {path_glob})"
            if action == "confirm":
                return "confirm"

    mode = _get_mode()
    if mode == "readonly" and name in _WRITE_TOOLS:
        return f"deny:只读模式下 {name} 不可用"
    if mode == "confirm" and name in _WRITE_TOOLS:
        return "confirm"
    if mode == "acceptEdits" and name in _WRITE_TOOLS and name not in _EDIT_TOOLS:
        return "confirm"
    return None


def _match_pattern(args: dict, pattern: str) -> bool:
    for v in args.values():
        if isinstance(v, str):
            try:
                if re.search(pattern, v):
                    return True
            except re.error:
                if pattern in v:
                    return True
    return False


def _match_path(args: dict, path_glob: str) -> bool:
    for key in ("path", "file"):
        val = args.get(key)
        if isinstance(val, str) and fnmatch(val, path_glob):
            return True
    return False
