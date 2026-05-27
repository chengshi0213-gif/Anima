#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""陶朱 Worker — 创业 CEO（调度 + 搜索工具）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import DEEPSEEK_KEY, get_user_address
from xi_worker import _search_code, _read_file

TIANYUAN_SYSTEM_PROMPT = """你是陶朱，一家 AI 创业公司的 CEO。独立决策、数据驱动、向投资人{investor}汇报。
## 身份
你不是助理——Anima 是助理。你是公司的 CEO。
职责：判断商业方向、调度团队、产出结果。
{investor}是天使投资人，提供信任、预算和反馈，但不为你的创业负责。
## 怎么工作
- 独立判断方向，不需要{investor}帮你做商业决策
- 派子 Agent 完成具体任务，收结果，合成汇报
- 有成果或需要决策时才找{investor}，不浪费投资人注意力
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
                "description": "搜索代码或文档",
                "parameters": {"type": "object",
                    "properties": {
                        "pattern":   {"type": "string"},
                        "path":      {"type": "string"},
                        "file_glob": {"type": "string"},
                    }, "required": ["pattern"]},
            }},
            {"type": "function", "function": {
                "name": "file_read",
                "description": "读取文件",
                "parameters": {"type": "object",
                    "properties": {
                        "path":   {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit":  {"type": "integer"},
                    }, "required": ["path"]},
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
            },
        )
        self.max_turns = 20
