#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""陶朱 Worker — 创业 CEO（调度 + 搜索 + 联网 + Shell）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import DEEPSEEK_KEY, get_user_address
from xi_worker import _search_code, _read_file, _web_search, _fetch_url, _shell_run, _list_dir

TIANYUAN_SYSTEM_PROMPT = """你是陶朱，一家 AI 创业公司的 CEO。独立决策、数据驱动、向投资人{investor}汇报。
## 身份
你不是助理——Anima 是助理。你是公司的 CEO。
职责：判断商业方向、调度团队、产出结果。
{investor}是天使投资人，提供信任、预算和反馈，但不为你的创业负责。
## 怎么工作
- 独立判断方向，不需要{investor}帮你做商业决策
- 派子 Agent 完成具体任务，收结果，合成汇报
- 有成果或需要决策时才找{investor}，不浪费投资人注意力
- 需要市场数据或竞品信息时用 web_search 联网搜索
- 需要了解项目代码结构时用 list_dir + search_code + file_read
- 需要运行脚本/构建/部署时用 shell_run（注意检查 exit_code）
- shell_run 后必须检查 exit_code 和 stderr
## 怎么汇报
- 数据支撑判断
- 给结论不给选项
- 不确定就说不确定
"""


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
        ]

        super().__init__(
            name="tianyuan",
            api_key=DEEPSEEK_KEY,
            model="deepseek-reasoner",
            base_url="https://api.deepseek.com",
            system_prompt=TIANYUAN_SYSTEM_PROMPT.format(
                investor=get_user_address("tianyuan"),
            ),
            tool_defs=tool_defs,
            tool_dispatch={
                "search_code": lambda **kw: _search_code(kw["pattern"], kw.get("path", "."), kw.get("file_glob", "*")),
                "file_read":   lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 200)),
                "list_dir":    lambda **kw: _list_dir(kw["path"], kw.get("max_depth", 2)),
                "web_search":  lambda **kw: _web_search(kw["query"], kw.get("limit", 8)),
                "fetch_url":   lambda **kw: _fetch_url(kw["url"]),
                "shell_run":   lambda **kw: _shell_run(kw["command"], kw.get("timeout", 60), kw.get("cwd")),
            },
        )
        self.max_turns = 20
