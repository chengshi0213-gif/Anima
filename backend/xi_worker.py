#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anima Worker — 私人助理（核心 Agent）
继承 AgentBase，带完整编程工具集
"""
import sys, subprocess, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase, PermissionRequest
from config import DEEPSEEK_KEY, WORKSPACE_DIR, get_user_address
from persona import compose_base_prompt

# ── 工具实现 ──────────────────────────────────────────────────────────────────

def _list_dir(path: str, max_depth: int = 2) -> dict:
    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"路径不存在: {path}"}
        items = []
        for item in p.rglob("*"):
            depth = len(item.relative_to(p).parts)
            if depth > max_depth:
                continue
            items.append({
                "path": str(item),
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
        return {"path": path, "items": items[:200]}
    except Exception as e:
        return {"error": str(e)}

def _read_file(path: str, offset: int = 0, limit: int = 200) -> dict:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        sliced = lines[offset:offset + limit]
        return {"path": path, "content": "\n".join(sliced),
                "total_lines": len(lines), "offset": offset, "shown": len(sliced)}
    except Exception as e:
        return {"error": str(e)}

def _write_file(path: str, content: str) -> dict:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"path": path, "bytes": len(content.encode())}
    except Exception as e:
        return {"error": str(e)}

def _edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
    try:
        p = Path(path)
        content = p.read_text(encoding="utf-8")
        if old_string not in content:
            return {"error": f"未找到目标字符串（前30字符）: {old_string[:30]!r}"}
        if replace_all:
            new_content = content.replace(old_string, new_string)
            count = content.count(old_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            count = 1
        p.write_text(new_content, encoding="utf-8")
        return {"path": path, "replaced": count}
    except Exception as e:
        return {"error": str(e)}

def _search_code(pattern: str, path: str = ".", file_glob: str = "*", limit: int = 30) -> dict:
    try:
        import re
        results = []
        for fpath in Path(path).rglob(file_glob):
            if not fpath.is_file() or fpath.stat().st_size > 2_000_000:
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if re.search(pattern, line):
                        results.append({"file": str(fpath), "line": i, "content": line.strip()})
                        if len(results) >= limit:
                            return {"results": results, "truncated": True}
            except Exception:
                pass
        return {"results": results, "truncated": False}
    except Exception as e:
        return {"error": str(e)}

_FORBIDDEN = {"rm -rf /", "format", "del /f /s /q c:\\", "shutdown", "mkfs", ":(){:|:&};:"}

def _shell_run(command: str, timeout: int = 60, cwd: str | None = None) -> dict:
    low = command.lower()
    if any(bad in low for bad in _FORBIDDEN):
        return {"error": f"命令被安全策略拒绝: {command[:80]}"}
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd or str(WORKSPACE_DIR),
            encoding="utf-8", errors="replace",
        )
        return {
            "exit_code": result.returncode,
            "stdout":    result.stdout[:3000],
            "stderr":    result.stderr[:1000],
        }
    except subprocess.TimeoutExpired:
        return {"error": f"命令超时（{timeout}s）", "exit_code": -1}
    except Exception as e:
        return {"error": str(e), "exit_code": -1}


# 联网检索已抽到共享模块 websearch.py（统一配额 + 缓存）。
# 这里保留同名别名，兼容历史 `from xi_worker import _web_search, _fetch_url`。
from websearch import web_search as _web_search, fetch_url as _fetch_url  # noqa: E402


class XiWorker(AgentBase):
    def __init__(self):
        tool_defs = [
            {"type": "function", "function": {
                "name": "list_dir",
                "description": "列出目录内容（递归，可指定深度）",
                "parameters": {"type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_depth": {"type": "integer", "description": "最大深度（默认2）"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "file_read",
                "description": "读取文件内容（支持行范围）",
                "parameters": {"type": "object",
                    "properties": {
                        "path":   {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit":  {"type": "integer"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "file_write",
                "description": "创建或覆盖文件",
                "parameters": {"type": "object",
                    "properties": {
                        "path":    {"type": "string"},
                        "content": {"type": "string"},
                    }, "required": ["path", "content"]},
            }},
            {"type": "function", "function": {
                "name": "file_edit",
                "description": "SEARCH/REPLACE 精确编辑文件",
                "parameters": {"type": "object",
                    "properties": {
                        "path":        {"type": "string"},
                        "old_string":  {"type": "string"},
                        "new_string":  {"type": "string"},
                        "replace_all": {"type": "boolean"},
                    }, "required": ["path", "old_string", "new_string"]},
            }},
            {"type": "function", "function": {
                "name": "search_code",
                "description": "用正则搜索文件内容",
                "parameters": {"type": "object",
                    "properties": {
                        "pattern":   {"type": "string"},
                        "path":      {"type": "string"},
                        "file_glob": {"type": "string"},
                        "limit":     {"type": "integer"},
                    }, "required": ["pattern"]},
            }},
            {"type": "function", "function": {
                "name": "shell_run",
                "description": "执行 shell 命令",
                "parameters": {"type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer"},
                        "cwd":     {"type": "string"},
                    }, "required": ["command"]},
            }},
            {"type": "function", "function": {
                "name": "web_search",
                "description": "联网搜索。使用 Tavily 或 Serper 搜索实时信息、新闻、文档等。需要配置搜索 API Key。",
                "parameters": {"type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索查询词"},
                        "limit": {"type": "integer", "description": "最多返回结果数（默认8）"},
                    }, "required": ["query"]},
            }},
            {"type": "function", "function": {
                "name": "fetch_url",
                "description": "读取指定 URL 的网页正文内容。使用 Jina AI Reader 获得更好的结构化提取。",
                "parameters": {"type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "要读取的网页 URL"},
                    }, "required": ["url"]},
            }},
        ]

        super().__init__(
            name="xi",
            api_key=DEEPSEEK_KEY,
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            system_prompt=compose_base_prompt("xi"),
            tool_defs=tool_defs,
            tool_dispatch={
                "list_dir":    lambda **kw: _list_dir(kw["path"], kw.get("max_depth", 2)),
                "file_read":   lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 200)),
                "file_write":  lambda **kw: _write_file(kw["path"], kw["content"]),
                "file_edit":   lambda **kw: _edit_file(kw["path"], kw["old_string"], kw["new_string"], kw.get("replace_all", False)),
                "search_code": lambda **kw: _search_code(kw["pattern"], kw.get("path", "."), kw.get("file_glob", "*"), kw.get("limit", 30)),
                "shell_run":   lambda **kw: _shell_run(kw["command"], kw.get("timeout", 60), kw.get("cwd")),
                "web_search":  lambda **kw: _web_search(kw["query"], kw.get("limit", 8)),
                "fetch_url":   lambda **kw: _fetch_url(kw["url"]),
            },
        )
        # 聊天人格：回复去 AI 味（清洗 Markdown 装饰符号），温度略高更自然
        self.humanize_output = True
        self.temperature = 0.7
