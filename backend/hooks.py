#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hooks.py — M14 内核3：工具钩子（pre_tool / post_tool），挂在 _execute_tool 唯一咽喉。

config 驱动；默认无钩子 = 零行为变化。仿 Claude Code：每个钩子可以是
  · {"python": "module:func"}   —— 调本地 Python 函数（同步或 async），传入 payload dict
  · {"shell":  "command"}       —— 跑 shell 命令，payload 以 JSON 喂 stdin
可选 {"match": "file_write"} 只对特定工具触发。

用例：file_write 后自动 black/prettier 格式化；pre_tool 拦截写敏感路径
（python 钩子返回 {"block": "原因"} 即否决工具执行）。

config 形态（security.hooks）：
  security:
    hooks:
      pre_tool:
        - {match: file_write, python: "myhooks:guard_path"}
      post_tool:
        - {match: file_write, shell: "black {path}"}   # {path} 等占位由钩子自己解析 payload
"""
from __future__ import annotations

import asyncio
import importlib
import json


def _hooks(event: str) -> list:
    try:
        from config import _get
        h = _get("security.hooks", {}) or {}
    except Exception:
        h = {}
    val = h.get(event, [])
    return val if isinstance(val, list) else []


async def run_pre_tool(name: str, args: dict, ctx: dict) -> dict | None:
    """跑 pre_tool 钩子。任一钩子返回 {'block': reason} → 返回 veto dict 阻止工具；
    否则 None（放行）。钩子异常一律吞掉（不因坏钩子卡死主流程）。"""
    payload = {"event": "pre_tool", "tool": name, "args": args,
               "session_id": ctx.get("session_id"), "agent": ctx.get("agent")}
    for spec in _hooks("pre_tool"):
        try:
            out = await _run_hook(spec, payload)
            if isinstance(out, dict) and out.get("block"):
                return {"error": f"被 hook 拦截: {out.get('block')}", "blocked": True}
        except Exception:
            pass
    return None


async def run_post_tool(name: str, args: dict, result: dict, ctx: dict) -> None:
    """跑 post_tool 钩子（如自动格式化）。结果不影响工具返回；异常吞掉。"""
    payload = {"event": "post_tool", "tool": name, "args": args, "result": result,
               "session_id": ctx.get("session_id"), "agent": ctx.get("agent")}
    for spec in _hooks("post_tool"):
        try:
            await _run_hook(spec, payload)
        except Exception:
            pass


async def _run_hook(spec, payload: dict):
    if not isinstance(spec, dict):
        return None
    match = spec.get("match")
    if match and match != payload.get("tool"):
        return None
    if "python" in spec:
        return await _call_python(spec["python"], payload)
    if "shell" in spec:
        return await _call_shell(spec["shell"], payload)
    return None


async def _call_python(mod_fn: str, payload: dict):
    mod_name, _, fn_name = str(mod_fn).partition(":")
    if not mod_name or not fn_name:
        return None
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, fn_name)
    res = fn(payload)
    if asyncio.iscoroutine(res):
        res = await res
    return res


async def _call_shell(cmd: str, payload: dict, timeout: int = 30):
    proc = await asyncio.create_subprocess_shell(
        cmd, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
            timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return {"error": "hook 超时"}
    return {"exit_code": proc.returncode,
            "stdout": (out or b"").decode("utf-8", "replace")[:1000]}
