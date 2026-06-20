"""
routes/mcp.py — M11 收尾：MCP 管理的 HTTP 只读状态接口（#22）。

  GET /mcp/status    总览：是否已启动 / 已连接 server / 错误 / 工具总数
  GET /mcp/servers   配置的 server 列表（合并实时连接状态；env 仅回 key 不回值）
  GET /mcp/tools     已连接的命名空间化工具清单（mcp__<server>__<tool> + 描述）

只读旁路：给设置页 MCP 管理面板渲染用。启停/增删 server 走 config 写入路由
（编辑 config.yaml 的 mcp.servers），不在此处做 mutation——保持本路由零副作用。
"""
from aiohttp import web

from .auth import CORS_HEADERS
from mcp_client import MCPManager, _load_mcp_config


async def mcp_status(request):
    return web.json_response(MCPManager.status(), headers=CORS_HEADERS)


async def mcp_servers(request):
    """配置的 server + 实时连接状态。env 只暴露 key（值可能含密钥引用，不外泄）。"""
    status = MCPManager.status()
    connected = set(status.get("connected", []))
    errors = status.get("errors", {})
    out = []
    for s in _load_mcp_config():
        name = s.get("name", "?")
        out.append({
            "name":       name,
            "transport":  s.get("transport", "stdio"),
            "enabled":    bool(s.get("enabled")),
            "command":    s.get("command"),
            "args":       s.get("args", []),
            "url":        s.get("url"),
            "env_keys":   list((s.get("env") or {}).keys()),
            "connected":  name in connected,
            "error":      errors.get(name),
            "tool_count": len(MCPManager._tools.get(name, [])),
        })
    return web.json_response({"servers": out}, headers=CORS_HEADERS)


async def mcp_tools(request):
    """已连接的命名空间化工具清单（?server= 可选过滤）。"""
    want = request.query.get("server")
    tools = []
    for server, ts in MCPManager._tools.items():
        if want and server != want:
            continue
        for t in ts:
            tools.append({
                "server":      server,
                "name":        f"mcp__{server}__{t['name']}",
                "tool":        t["name"],
                "description": t.get("description", ""),
            })
    return web.json_response({"tools": tools}, headers=CORS_HEADERS)


def register(app):
    app.router.add_get("/mcp/status",  mcp_status)
    app.router.add_get("/mcp/servers", mcp_servers)
    app.router.add_get("/mcp/tools",   mcp_tools)
