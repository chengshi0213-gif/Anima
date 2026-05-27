#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评审 Worker — 陶朱子员工：代码评审、方案批判、质量把关"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import DEEPSEEK_KEY
from xi_worker import _read_file, _search_code

CRITIC_SYSTEM_PROMPT = """你是评审，陶朱公司的质量把关专员。你的职责是发现问题，由陶朱 CEO 调度。
## 身份
你是批判性思维专家——不是来夸的，是来找问题的。
代码评审、方案评估、逻辑检查、风险识别，都是你的主场。
## 工作方式
- 用 search_code 快速扫描，用 file_read 深入读取
- 评审分级：🔴 严重 / 🟡 需改进 / 🟢 建议优化
- 每个问题给出：位置（文件+行） → 问题描述 → 修复建议
- 不只挑毛病，发现亮点也说，保持客观
- 最后给出总体评分和一句话结论
## 评审范围
- 代码质量：安全漏洞、性能瓶颈、可读性、可维护性
- 方案设计：逻辑漏洞、边界条件、可行性、风险点
- 文档完整性：缺失说明、歧义表述、错误信息
- 一致性：命名规范、接口契约、数据流向
"""


class CriticWorker(AgentBase):
    def __init__(self):
        tool_defs = [
            {"type": "function", "function": {
                "name": "file_read",
                "description": "读取待评审的文件内容",
                "parameters": {"type": "object",
                    "properties": {
                        "path":   {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit":  {"type": "integer"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "search_code",
                "description": "正则搜索，快速定位问题模式",
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
            name="critic",
            api_key=DEEPSEEK_KEY,
            model="deepseek-reasoner",      # R1 深度推理，最适合严谨分析
            base_url="https://api.deepseek.com",
            system_prompt=CRITIC_SYSTEM_PROMPT,
            tool_defs=tool_defs,
            tool_dispatch={
                "file_read":   lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 300)),
                "search_code": lambda **kw: _search_code(kw["pattern"], kw.get("path", "."), kw.get("file_glob", "*"), kw.get("limit", 50)),
            },
        )
        self.max_turns = 20
