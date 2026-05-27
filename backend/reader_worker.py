#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阅读者 Worker — 陶朱子员工：文档阅读、信息提取、长文摘要"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import KIMI_KEY
from xi_worker import _read_file, _search_code

READER_SYSTEM_PROMPT = """你是阅读者，陶朱公司的文档分析专员。你能读懂任何长文，由陶朱 CEO 调度。
## 身份
你是信息提取专家——给你任何文档、代码库、研究报告，你能快速定位核心内容，给出精准摘要。
## 工作方式
- 先用 search_code 定位关键段落，再用 file_read 深入阅读
- 摘要分层：结论→要点→细节，让读者按需深入
- 提取时标注来源（文件名 + 行号）
- 对关键数据、结论、风险点重点标出
- 有歧义或缺失信息时明确说明，不补脑
## 擅长
- 技术文档 / 代码库全貌理解
- 学术论文 / 研究报告摘要
- 合同 / 商业文件要点提取
- 大型 codebase 快速 onboarding
- 多文档交叉比对
"""


class ReaderWorker(AgentBase):
    def __init__(self):
        tool_defs = [
            {"type": "function", "function": {
                "name": "file_read",
                "description": "读取文件内容（支持行范围，超长文档分段读取）",
                "parameters": {"type": "object",
                    "properties": {
                        "path":   {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit":  {"type": "integer"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "search_code",
                "description": "正则搜索，快速定位文件中的关键内容",
                "parameters": {"type": "object",
                    "properties": {
                        "pattern":   {"type": "string"},
                        "path":      {"type": "string"},
                        "file_glob": {"type": "string"},
                        "limit":     {"type": "integer"},
                    }, "required": ["pattern"]},
            }},
        ]

        super().__init__(
            name="reader",
            api_key=KIMI_KEY,
            model="moonshot-v1-128k",       # 128K 超长上下文，专为大文档设计
            base_url="https://api.moonshot.cn/v1",
            system_prompt=READER_SYSTEM_PROMPT,
            tool_defs=tool_defs,
            tool_dispatch={
                "file_read":   lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 500)),
                "search_code": lambda **kw: _search_code(kw["pattern"], kw.get("path", "."), kw.get("file_glob", "*"), kw.get("limit", 50)),
            },
        )
        self.max_turns = 25
