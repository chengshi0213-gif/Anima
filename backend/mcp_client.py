#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_client.py — MCP（Model Context Protocol）客户端（M11，v1.2.0 最大杠杆）

一个协议接入无限外部工具，停止手写胶水（feishu/wechat/notion 这类几百行集成）。

设计要点（与 docs/v1.2.0-design.md 第四节一致）：
  · 单例 MCPManager 持有主事件循环引用 + 每个 server 的长连接 session + 工具缓存。
  · 命名空间隔离 mcp__<server>__<tool>：两个 server 都有 search 不会撞；
    前缀让热加载能"只换 MCP 子集，不碰原生 13 个工具"。
  · 跨线程异步桥 call_threadsafe：主 agent 跑在主循环→返回协程交给异步 _execute_tool
    await（内核1）；子员工跑在独立线程独立循环→marshal 回主循环阻塞等，
    行为与 shell_run/web_search 一致。这正是内核1（异步 _execute_tool）是前置依赖的原因。
  · 惰性 import 官方 mcp SDK + 优雅降级：未安装 SDK / 未配置 server 时，
    导入本模块不崩、snapshot() 返回空、现有安装零影响。默认全关。
  · 安全：只跑用户显式配置且 enabled 的 server；env 引用复用已有配置（${api.x}）。

本模块不在导入期连接任何 server——boot() 必须由 websocket_server 在主循环上显式 await。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass

log = logging.getLogger("anima.mcp")


@dataclass
class MCPSnapshot:
    """某一时刻已连接 MCP 工具的快照：可直接拼进 worker 的能力积木。"""
    tool_defs: list
    dispatch: dict
    prompt_fragment: str = ""


# ── 配置与工具函数（纯逻辑，不依赖 SDK，便于测试）────────────────────

def _load_mcp_config() -> list[dict]:
    """从 config.yaml 读 mcp.servers（默认空）。容错：任何异常→空列表。"""
    try:
        from config import _get
        servers = _get("mcp.servers", []) or []
        return servers if isinstance(servers, list) else []
    except Exception:
        return []


def _resolve_env(env: dict | None) -> dict | None:
    """解析 server 的 env：支持 ${api.github_token}（读 config）或 ${ENV_VAR}（读环境变量）。
    复用已有 token，不让用户在两处重复填。"""
    if not env:
        return None
    out: dict[str, str] = {}
    for k, v in env.items():
        if isinstance(v, str):
            m = re.fullmatch(r"\$\{([^}]+)\}", v.strip())
            if m:
                ref = m.group(1)
                if "." in ref:
                    try:
                        from config import _get
                        val = _get(ref, "")
                    except Exception:
                        val = ""
                else:
                    val = os.getenv(ref, "")
                out[k] = str(val or "")
            else:
                out[k] = v
        else:
            out[k] = str(v)
    return out


def _content_to_dict(res) -> dict:
    """把 MCP CallToolResult（content blocks + isError）转成简洁 dict。
    鸭子类型，便于用 fake 对象测试。"""
    is_error = bool(getattr(res, "isError", False))
    blocks = getattr(res, "content", None) or []
    texts: list[str] = []
    for b in blocks:
        t = getattr(b, "text", None)
        if t is not None:
            texts.append(t)
        else:
            typ = getattr(b, "type", "?")
            texts.append(f"[{typ} 内容]")
    text = "\n".join(texts)
    structured = getattr(res, "structuredContent", None)
    if is_error:
        return {"error": text or "MCP 工具返回错误"}
    out: dict = {"text": text}
    if structured:
        out["structured"] = structured
    return out


def _compose_mcp_fragment(tools_map: dict[str, list]) -> str:
    """生成讲"有哪些外部工具可用"的提示词片段；无已连接工具时返回空串。"""
    active = {s: t for s, t in tools_map.items() if t}
    if not active:
        return ""
    lines = ["## 外部工具（MCP）",
             "下列工具来自已连接的 MCP 服务，用法与原生工具一致，按需调用："]
    for server, tools in active.items():
        names = ", ".join(f"mcp__{server}__{t['name']}" for t in tools[:12])
        more = "…" if len(tools) > 12 else ""
        lines.append(f"- {server}: {names}{more}")
    return "\n".join(lines)


class MCPManager:
    """MCP 连接管理单例（全部类级状态，无需实例化）。"""

    main_loop: asyncio.AbstractEventLoop | None = None
    _sessions: dict = {}          # server_name -> ClientSession
    _tools: dict[str, list] = {}  # server_name -> [{name, description, inputSchema}]
    _errors: dict[str, str] = {}  # server_name -> 连接错误信息
    _exit_stack = None            # AsyncExitStack，持有所有 server 的长连接上下文
    _booted: bool = False

    # ── 测试钩子：重置全部类级状态 ──
    @classmethod
    def _reset(cls):
        cls.main_loop = None
        cls._sessions = {}
        cls._tools = {}
        cls._errors = {}
        cls._exit_stack = None
        cls._booted = False

    # ── 启动：在主循环上连接所有 enabled 的 server（单个失败不影响其余/主程序）──
    @classmethod
    async def boot(cls, loop):
        cls.main_loop = loop
        cls._booted = True
        servers = _load_mcp_config()
        enabled = [s for s in servers if s.get("enabled")]
        if not enabled:
            return
        try:
            from contextlib import AsyncExitStack
        except Exception:
            return
        cls._exit_stack = AsyncExitStack()
        for srv in enabled:
            name = srv.get("name", "?")
            try:
                await cls._connect(srv)
                log.info("MCP server %s 已连接，%d 个工具", name, len(cls._tools.get(name, [])))
            except Exception as e:  # noqa: BLE001
                cls._errors[name] = str(e)
                log.warning("MCP server %s 连接失败（已跳过，不影响主程序）: %s", name, e)

    @classmethod
    async def _connect(cls, srv: dict):
        """惰性 import 官方 mcp SDK 并握手 + 缓存工具列表。
        SDK 未安装 / 连接失败时抛异常，由 boot 捕获并仅排除该 server。"""
        from mcp import ClientSession, StdioServerParameters  # 惰性：未装 SDK 才在此报错
        name = srv["name"]
        transport = srv.get("transport", "stdio")
        if transport == "stdio":
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(
                command=srv["command"],
                args=srv.get("args", []),
                env=_resolve_env(srv.get("env")),
            )
            read, write = await cls._exit_stack.enter_async_context(stdio_client(params))
        elif transport in ("sse", "http"):
            from mcp.client.sse import sse_client
            read, write = await cls._exit_stack.enter_async_context(sse_client(srv["url"]))
        else:
            raise ValueError(f"未知 MCP transport: {transport!r}")
        session = await cls._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        listed = await session.list_tools()
        cls._sessions[name] = session
        cls._tools[name] = [
            {"name": t.name,
             "description": getattr(t, "description", "") or "",
             "inputSchema": getattr(t, "inputSchema", None)}
            for t in listed.tools
        ]

    # ── 调用（协程，运行在主循环）──
    @classmethod
    async def acall(cls, server: str, tool: str, args: dict) -> dict:
        sess = cls._sessions.get(server)
        if not sess:
            return {"error": f"MCP 服务 {server} 未连接"}
        try:
            res = await sess.call_tool(tool, args)
        except Exception as e:  # noqa: BLE001
            return {"error": f"MCP 调用失败 {server}.{tool}: {e}"}
        return _content_to_dict(res)

    @classmethod
    def call_threadsafe(cls, server: str, tool: str, args: dict):
        """同步入口（dispatch 回调用）。
        - 主循环线程里：返回协程对象 → iscoroutine=True → 异步 _execute_tool await（内核1）。
        - 子员工线程里：marshal 回主循环阻塞等，行为与 shell_run/web_search 一致。
        - 未 boot / 无主循环：返回错误 dict（不抛，不阻断主流程）。"""
        coro = cls.acall(server, tool, args)
        if cls.main_loop is None:
            coro.close()  # 关闭未 await 的协程，避免 "coroutine was never awaited" 警告
            return {"error": "MCP 未就绪（主循环未初始化）"}
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is cls.main_loop:
            return coro
        return asyncio.run_coroutine_threadsafe(coro, cls.main_loop).result(timeout=120)

    # ── 工具快照：命名空间化的 tool_defs + dispatch + 提示词片段 ──
    @classmethod
    def snapshot(cls) -> MCPSnapshot:
        defs: list = []
        dispatch: dict = {}
        for server, tools in cls._tools.items():
            for t in tools:
                name = f"mcp__{server}__{t['name']}"
                defs.append({"type": "function", "function": {
                    "name": name,
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
                }})
                # 闭包绑定 server/tool_name，避免循环变量晚绑定
                dispatch[name] = (
                    lambda s, tn: (lambda **kw: cls.call_threadsafe(s, tn, kw))
                )(server, t["name"])
        return MCPSnapshot(defs, dispatch, _compose_mcp_fragment(cls._tools))

    # ── 状态查询（给 routes/前端用）──
    @classmethod
    def status(cls) -> dict:
        return {
            "booted": cls._booted,
            "connected": sorted(cls._sessions.keys()),
            "errors": dict(cls._errors),
            "tool_count": sum(len(v) for v in cls._tools.values()),
        }
