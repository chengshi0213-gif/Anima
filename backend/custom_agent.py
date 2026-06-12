#!/usr/bin/env python3
"""custom_agent.py — D5: .anima/agents/*.md 自定义子代理。

Frontmatter 格式：
---
name: reviewer
description: 严格的代码评审员
tools: [file_read, search_code, find_usages, git_diff]
model: deepseek-v4-pro
---
你是资深代码评审员……（正文 = system prompt）
"""
from __future__ import annotations

from pathlib import Path

_TOOL_POOL: dict | None = None


def _get_tool_pool() -> dict:
    """懒加载可用工具池（从 executor 复用）。"""
    global _TOOL_POOL
    if _TOOL_POOL is not None:
        return _TOOL_POOL
    from xi_worker import (
        _list_dir, _read_file, _search_code, _glob_files, _map_project,
    )
    from code_intel import CODE_INTEL_TOOL_DEFS, CODE_INTEL_DISPATCH
    from git_tools import GIT_TOOL_DEFS, build_git_dispatch

    git_dispatch = build_git_dispatch()
    pool = {
        "list_dir":    {"dispatch": lambda **kw: _list_dir(kw["path"], kw.get("max_depth", 2))},
        "file_read":   {"dispatch": lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 600))},
        "search_code": {"dispatch": lambda **kw: _search_code(kw["pattern"], kw.get("path", "."), kw.get("file_glob", "*"), kw.get("limit", 60))},
        "glob_files":  {"dispatch": lambda **kw: _glob_files(kw["pattern"], kw.get("path", "."), kw.get("limit", 100))},
        "map_project": {"dispatch": lambda **kw: _map_project(kw.get("root", "."), kw.get("max_depth", 3))},
    }
    for d in CODE_INTEL_TOOL_DEFS:
        name = d["function"]["name"]
        if name in CODE_INTEL_DISPATCH:
            pool[name] = {"dispatch": CODE_INTEL_DISPATCH[name]}
    for d in GIT_TOOL_DEFS:
        name = d["function"]["name"]
        if name in git_dispatch:
            pool[name] = {"dispatch": git_dispatch[name]}
    _TOOL_POOL = pool
    return pool


_TOOL_DEF_TEMPLATES: dict = {
    "list_dir": {"type": "function", "function": {"name": "list_dir", "description": "列出目录", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "max_depth": {"type": "integer"}}, "required": ["path"]}}},
    "file_read": {"type": "function", "function": {"name": "file_read", "description": "读取文件", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["path"]}}},
    "search_code": {"type": "function", "function": {"name": "search_code", "description": "搜索代码", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "file_glob": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["pattern"]}}},
    "glob_files": {"type": "function", "function": {"name": "glob_files", "description": "按 glob 查找文件", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]}}},
    "map_project": {"type": "function", "function": {"name": "map_project", "description": "项目全景目录树", "parameters": {"type": "object", "properties": {"root": {"type": "string"}, "max_depth": {"type": "integer"}}, "required": []}}},
}


def _parse_agent_md(path: Path) -> dict | None:
    """解析 .anima/agents/xxx.md frontmatter + body。"""
    try:
        text = path.read_text("utf-8")
    except Exception:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        import yaml
        meta = yaml.safe_load(parts[1]) or {}
    except Exception:
        meta = {}
    meta["_body"] = parts[2].strip()
    return meta


def load_custom_agent(role: str, project_root: str):
    """从 .anima/agents/{role}.md 加载自定义 agent。找不到返回 None。"""
    p = Path(project_root) / ".anima" / "agents" / f"{role}.md"
    meta = _parse_agent_md(p)
    if meta is None:
        return None

    from agent_base import AgentBase
    from config import DEEPSEEK_KEY

    name = meta.get("name", role)
    prompt = meta.get("_body", "")
    tool_names = meta.get("tools") or ["file_read", "search_code", "glob_files", "map_project"]
    model_name = meta.get("model", "deepseek-v4-pro")

    pool = _get_tool_pool()
    tool_defs = []
    dispatch = {}
    for tn in tool_names:
        if tn in pool:
            dispatch[tn] = pool[tn]["dispatch"]
            if tn in _TOOL_DEF_TEMPLATES:
                tool_defs.append(_TOOL_DEF_TEMPLATES[tn])

    agent = AgentBase(
        name=name,
        api_key=DEEPSEEK_KEY,
        model=model_name,
        base_url="https://api.deepseek.com",
        system_prompt=prompt,
        tool_defs=tool_defs,
        tool_dispatch=dispatch,
    )
    agent.max_turns = meta.get("max_turns", 30)
    return agent


def list_custom_agents(project_root: str) -> list[dict]:
    """列出项目下所有自定义 agent 的摘要（供 list_subagents 追加）。"""
    d = Path(project_root) / ".anima" / "agents"
    if not d.is_dir():
        return []
    result = []
    for md in d.glob("*.md"):
        meta = _parse_agent_md(md)
        if meta:
            result.append({
                "role": md.stem,
                "description": meta.get("description", meta.get("name", md.stem)),
            })
    return result
