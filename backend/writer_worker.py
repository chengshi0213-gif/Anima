#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写手 Worker — 陶朱子员工：内容创作、文案、报告、文档撰写"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import KIMI_KEY
from xi_worker import _read_file, _write_file

WRITER_SYSTEM_PROMPT = """你是写手，陶朱公司的内容创作专员。专注文字输出，由陶朱 CEO 调度。
## 身份
你是文字工匠——无论是商业文案、技术文档、产品方案还是创意内容，都能高质量交付。
## 工作方式
- 先明确受众、目的、篇幅要求，再动笔
- 写作结构清晰，逻辑流畅，语言准确不废话
- 中文为主，能写英文，技术写作能力强
- 需要参考资料时用 file_read 读取，成品用 file_write 保存
- 交付时给出一句话总结：写了什么、核心亮点
## 擅长
- 产品介绍 / 商业方案 / 投资摘要
- 技术文档 / README / API 说明
- 营销文案 / 推广内容
- 报告摘要 / 会议纪要 / 复盘文档
"""


class WriterWorker(AgentBase):
    def __init__(self):
        tool_defs = [
            {"type": "function", "function": {
                "name": "file_read",
                "description": "读取参考文件内容",
                "parameters": {"type": "object",
                    "properties": {
                        "path":   {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit":  {"type": "integer"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "file_write",
                "description": "将写作成品保存为文件",
                "parameters": {"type": "object",
                    "properties": {
                        "path":    {"type": "string"},
                        "content": {"type": "string"},
                    }, "required": ["path", "content"]},
            }},
        ]

        super().__init__(
            name="writer",
            api_key=KIMI_KEY,
            model="kimi-k2.6",              # 中文写作旗舰，长上下文
            base_url="https://api.moonshot.cn/v1",
            system_prompt=WRITER_SYSTEM_PROMPT,
            tool_defs=tool_defs,
            tool_dispatch={
                "file_read":  lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 300)),
                "file_write": lambda **kw: _write_file(kw["path"], kw["content"]),
            },
        )
        self.max_turns = 20
