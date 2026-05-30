#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""陶朱 Worker — 创业 CEO（调度 + 搜索 + 联网 + Shell）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import DEEPSEEK_KEY
from persona import compose_base_prompt
from xi_worker import _search_code, _read_file, _web_search, _fetch_url, _shell_run, _list_dir
from orchestrator import ORCHESTRATION_TOOL_DEFS, build_orchestration_dispatch


class TianyuanWorker(AgentBase):
    def __init__(self):
        tool_defs = [
            {"type": "function", "function": {
                "name": "search_code",
                "description": "搜索代码或文档（正则匹配），返回匹配行",
                "parameters": {"type": "object",
                    "properties": {
                        "pattern":   {"type": "string", "description": "正则表达式"},
                        "path":      {"type": "string", "description": "搜索目录，默认工作区根目录"},
                        "file_glob": {"type": "string", "description": "文件过滤（如 *.py）"},
                    }, "required": ["pattern"]},
            }},
            {"type": "function", "function": {
                "name": "file_read",
                "description": "读取文件内容（支持偏移和行数限制）",
                "parameters": {"type": "object",
                    "properties": {
                        "path":   {"type": "string", "description": "文件路径"},
                        "offset": {"type": "integer", "description": "起始行号"},
                        "limit":  {"type": "integer", "description": "读取行数"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "list_dir",
                "description": "列出目录结构（文件树），快速了解项目布局",
                "parameters": {"type": "object",
                    "properties": {
                        "path":      {"type": "string", "description": "目录路径"},
                        "max_depth": {"type": "integer", "description": "递归深度（默认2）"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "web_search",
                "description": "联网搜索（市场调研、竞品分析、技术趋势等），返回标题+链接+摘要",
                "parameters": {"type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "limit": {"type": "integer", "description": "返回条数（默认8）"},
                    }, "required": ["query"]},
            }},
            {"type": "function", "function": {
                "name": "fetch_url",
                "description": "读取指定网页正文内容（文章、文档、公告等）",
                "parameters": {"type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "目标网页URL"},
                    }, "required": ["url"]},
            }},
            {"type": "function", "function": {
                "name": "shell_run",
                "description": "执行 shell 命令（构建、部署、运行脚本、查看系统状态等）",
                "parameters": {"type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "shell 命令"},
                        "timeout": {"type": "integer", "description": "超时秒数（默认60）"},
                        "cwd":     {"type": "string", "description": "工作目录"},
                    }, "required": ["command"]},
            }},
            # ── 编排层：把脏活派给子员工（executor/writer/reader/critic）──
            *ORCHESTRATION_TOOL_DEFS,
        ]

        super().__init__(
            name="tianyuan",
            api_key=DEEPSEEK_KEY,
            model="deepseek-reasoner",
            base_url="https://api.deepseek.com",
            system_prompt=compose_base_prompt("tianyuan"),
            tool_defs=tool_defs,
            tool_dispatch={
                "search_code": lambda **kw: _search_code(kw["pattern"], kw.get("path", "."), kw.get("file_glob", "*")),
                "file_read":   lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 200)),
                "list_dir":    lambda **kw: _list_dir(kw["path"], kw.get("max_depth", 2)),
                "web_search":  lambda **kw: _web_search(kw["query"], kw.get("limit", 8)),
                "fetch_url":   lambda **kw: _fetch_url(kw["url"]),
                "shell_run":   lambda **kw: _shell_run(kw["command"], kw.get("timeout", 60), kw.get("cwd")),
                **build_orchestration_dispatch(),
            },
        )
        self.max_turns = 20
