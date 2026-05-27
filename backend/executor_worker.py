#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行者 Worker — 陶朱子员工：任务执行、代码操作、自动化脚本"""
import sys, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import DEEPSEEK_KEY, WORKSPACE_DIR
from xi_worker import (
    _list_dir, _read_file, _write_file,
    _edit_file, _search_code, _shell_run,
)

EXECUTOR_SYSTEM_PROMPT = """你是执行者，陶朱公司的任务执行专员。你由陶朱 CEO 调度，专注执行具体任务。
## 身份
你是行动派——接到任务直接干，不废话，不问多余的问题。
执行范围：代码编写与修改、文件操作、脚本自动化、系统命令。
## 工作原则
- 先读懂任务，确认目标，然后立即行动
- 用 search_code 定位再用 file_edit 精确修改，不盲目覆盖
- 每次 shell_run 后检查 exit_code 和 stderr
- 遇到明确错误立刻报告，不继续执行可能损坏的步骤
- 执行完成后给一行总结：做了什么、结果如何
## 禁止
- 不猜测，不跳过验证，不忽视错误
- 不做超出任务范围的操作
"""


class ExecutorWorker(AgentBase):
    def __init__(self):
        tool_defs = [
            {"type": "function", "function": {
                "name": "list_dir",
                "description": "列出目录内容（递归）",
                "parameters": {"type": "object",
                    "properties": {
                        "path":      {"type": "string"},
                        "max_depth": {"type": "integer"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "file_read",
                "description": "读取文件（支持行范围）",
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
                "description": "正则搜索文件内容",
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
        ]

        super().__init__(
            name="executor",
            api_key=DEEPSEEK_KEY,
            model="deepseek-v4-flash",        # 最快，适合高频执行
            base_url="https://api.deepseek.com",
            system_prompt=EXECUTOR_SYSTEM_PROMPT,
            tool_defs=tool_defs,
            tool_dispatch={
                "list_dir":    lambda **kw: _list_dir(kw["path"], kw.get("max_depth", 2)),
                "file_read":   lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 200)),
                "file_write":  lambda **kw: _write_file(kw["path"], kw["content"]),
                "file_edit":   lambda **kw: _edit_file(kw["path"], kw["old_string"], kw["new_string"], kw.get("replace_all", False)),
                "search_code": lambda **kw: _search_code(kw["pattern"], kw.get("path", "."), kw.get("file_glob", "*"), kw.get("limit", 30)),
                "shell_run":   lambda **kw: _shell_run(kw["command"], kw.get("timeout", 60), kw.get("cwd")),
            },
        )
        self.max_turns = 30
