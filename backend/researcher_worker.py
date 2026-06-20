#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究员 Worker — 陶朱子员工：联网检索、市场/竞品调研、资料搜集与交叉验证

填补的缺口：原四个子员工没有一个能联网搜索（只有陶朱自己挂了 Tavily），
导致 CEO 最高频的可委派活——调研——派不出去。本员工补上这一层。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import DEEPSEEK_KEY
from persona import _VOICE_CORE
from websearch import WEB_SEARCH_TOOL_DEFS, build_dispatch
from xi_worker import _read_file, _write_file

RESEARCHER_SYSTEM_PROMPT = """你是研究员，陶朱公司的调研专员，由陶朱 CEO 调度。

## 身份
你是信息侦察兵——市场规模、竞品动向、行业数据、政策法规、技术选型，你能联网查清楚并给出**带来源**的结论。

## 工作方式
1. 先拆解：把调研问题拆成几个可检索的子问题。
2. 多源检索：用 web_search 找信源，用 fetch_url 读关键网页正文。**不要只看摘要就下结论。**
3. 交叉验证：关键数字/结论至少两个独立来源对得上才采信；对不上就如实标注分歧。
4. 标注来源：每个关键事实后注明来源（站点/标题），区分"事实"与"推测"。
5. 需要时用 file_write 把调研报告存成文件交付。

## 禁止
- 不编造数据、不把单一来源当定论、不把"搜不到"说成"不存在"。
- 信息有时效性的，标注时间。

## 收尾
给分层结论：核心判断 → 关键数据(带来源) → 风险/不确定项。
""" + _VOICE_CORE


class ResearcherWorker(AgentBase):
    def __init__(self):
        tool_defs = [
            *WEB_SEARCH_TOOL_DEFS,
            {"type": "function", "function": {
                "name": "file_read",
                "description": "读取参考文件",
                "parameters": {"type": "object",
                    "properties": {
                        "path":   {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit":  {"type": "integer"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "file_write",
                "description": "保存调研报告为文件",
                "parameters": {"type": "object",
                    "properties": {
                        "path":    {"type": "string"},
                        "content": {"type": "string"},
                    }, "required": ["path", "content"]},
            }},
        ]

        super().__init__(
            name="researcher",
            api_key=DEEPSEEK_KEY,
            model="deepseek-v4-pro",          # 强综合/取舍能力，适合多源汇总
            base_url="https://api.deepseek.com",
            system_prompt=RESEARCHER_SYSTEM_PROMPT,
            tool_defs=tool_defs,
            tool_dispatch={
                **build_dispatch(),           # web_search + fetch_url
                "file_read":  lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 400)),
                "file_write": lambda **kw: _write_file(kw["path"], kw["content"]),
            },
        )
        self.max_turns = 25
        # 网页正文较长，放宽工具结果上限，避免把关键内容截没
        self.tool_result_cap = 8000
