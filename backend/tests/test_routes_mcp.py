#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_routes_mcp.py — #22 MCP 管理只读路由单测。

锁定不变量：
  · /mcp/status 默认（未 boot）→ booted False / connected [] / tool_count 0。
  · /mcp/servers 合并 config + 实时连接状态；env 只回 key 不回值（不外泄密钥）。
  · /mcp/tools 返回命名空间化工具名 mcp__<server>__<tool>，?server= 可过滤。

运行: cd backend && python -m pytest tests/test_routes_mcp.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).parent.parent))

import routes.mcp as mcp_routes  # noqa: E402
from mcp_client import MCPManager  # noqa: E402


def _body(resp):
    return json.loads(resp.body.decode())


def test_status_default():
    MCPManager._reset()
    resp = asyncio.run(mcp_routes.mcp_status(make_mocked_request("GET", "/mcp/status")))
    d = _body(resp)
    assert d["booted"] is False
    assert d["connected"] == []
    assert d["tool_count"] == 0


def test_servers_merges_config_and_masks_env(monkeypatch):
    MCPManager._reset()
    monkeypatch.setattr(mcp_routes, "_load_mcp_config", lambda: [{
        "name": "gh", "transport": "stdio", "command": "npx",
        "enabled": True, "env": {"GITHUB_TOKEN": "${api.github_token}"},
    }])
    MCPManager._tools = {"gh": [{"name": "search", "description": "d"}]}
    MCPManager._sessions = {"gh": object()}        # 模拟已连接
    resp = asyncio.run(mcp_routes.mcp_servers(make_mocked_request("GET", "/mcp/servers")))
    s = _body(resp)["servers"][0]
    assert s["name"] == "gh"
    assert s["enabled"] is True
    assert s["connected"] is True
    assert s["tool_count"] == 1
    # 关键：env 只暴露 key，不外泄值（哪怕是 ${...} 引用）
    assert s["env_keys"] == ["GITHUB_TOKEN"]
    assert "${api.github_token}" not in json.dumps(s)   # 值（密钥引用）不外泄，只回 key
    MCPManager._reset()


def test_tools_namespaced_and_filter():
    MCPManager._reset()
    MCPManager._tools = {
        "gh":  [{"name": "search", "description": "搜索"}],
        "fs":  [{"name": "read", "description": "读"}],
    }
    # 全量
    resp = asyncio.run(mcp_routes.mcp_tools(make_mocked_request("GET", "/mcp/tools")))
    names = {t["name"] for t in _body(resp)["tools"]}
    assert names == {"mcp__gh__search", "mcp__fs__read"}
    # ?server= 过滤
    resp2 = asyncio.run(mcp_routes.mcp_tools(make_mocked_request("GET", "/mcp/tools?server=gh")))
    tools2 = _body(resp2)["tools"]
    assert len(tools2) == 1 and tools2[0]["name"] == "mcp__gh__search"
    MCPManager._reset()
