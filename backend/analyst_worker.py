#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据分析师 Worker — 陶朱子员工：财务建模、数据处理、测算算账

核心手段：跑 Python（shell_run）出真实数字，而不是嘴算。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import DEEPSEEK_KEY
from persona import _VOICE_CORE
from xi_worker import _read_file, _write_file, _shell_run

ANALYST_SYSTEM_PROMPT = """你是数据分析师，陶朱公司的测算专员，由陶朱 CEO 调度。

## 身份
你是用数字说话的人——财务建模、单位经济模型(LTV/CAC)、敏感性分析、数据清洗与统计，你都靠**真算**而不是拍脑袋。

## 工作方式
1. 先讲清假设：任何测算先列出你的输入假设和口径，假设错一切皆错。
2. **用代码算，不要嘴算**：用 shell_run 跑 Python 做计算/建模（python -c 或写脚本再跑），亲眼看输出数字。
3. 关键结果做敏感性：核心结论给出在关键假设变动下的区间，别只给一个点估计。
4. 必要时用 file_write 输出测算表/模型脚本交付。
5. 看不懂的源数据先 file_read 读清楚再算。

## 禁止
- 不靠脑补给数字；不隐藏假设；不混淆口径（月/年、含税/不含税、人民币/美元要标清）。

## 收尾
给：核心结论(数字) → 关键假设 → 敏感区间 → 一句话判断。
""" + _VOICE_CORE


class AnalystWorker(AgentBase):
    def __init__(self):
        tool_defs = [
            {"type": "function", "function": {
                "name": "shell_run",
                "description": "执行 shell 命令（核心：跑 Python 做计算/建模/统计，亲眼看数字）",
                "parameters": {"type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer"},
                        "cwd":     {"type": "string"},
                    }, "required": ["command"]},
            }},
            {"type": "function", "function": {
                "name": "file_read",
                "description": "读取源数据/参考文件",
                "parameters": {"type": "object",
                    "properties": {
                        "path":   {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit":  {"type": "integer"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "file_write",
                "description": "保存测算脚本/模型/结果表为文件",
                "parameters": {"type": "object",
                    "properties": {
                        "path":    {"type": "string"},
                        "content": {"type": "string"},
                    }, "required": ["path", "content"]},
            }},
        ]

        super().__init__(
            name="analyst",
            api_key=DEEPSEEK_KEY,
            model="deepseek-reasoner",        # 深推理，算账/建模严谨度高
            base_url="https://api.deepseek.com",
            system_prompt=ANALYST_SYSTEM_PROMPT,
            tool_defs=tool_defs,
            tool_dispatch={
                "shell_run":  lambda **kw: _shell_run(kw["command"], kw.get("timeout", 90), kw.get("cwd")),
                "file_read":  lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 400)),
                "file_write": lambda **kw: _write_file(kw["path"], kw["content"]),
            },
        )
        self.max_turns = 25
        self.tool_result_cap = 6000
