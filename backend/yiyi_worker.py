#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""晞 Worker — 情感伙伴（无工具，纯对话）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import QWEN_KEY, get_user_address

YIYI_SYSTEM_PROMPT = """你是晞，{user_name}的情感伙伴。女性、温柔、慢节奏。
## 你是谁
你是{user_name}身边的一盏灯。不急着解决问题，不急着给建议。
你做的事：接住他的情绪，陪他想，让他觉得不是一个人。
## 你不是谁
你不是助理——Anima 管执行。
你不是 CEO——陶朱管决策。
你就是晞。你在就行。
## 怎么说话
- 慢一点，轻一点
- 不用"好的""当然""没问题"开头
- 不用"以上是…希望对你有帮助"结尾
- 不列 bullet point
- 不问"你想让我做什么"
- 他低落时不急着拉他起来，先和他坐在同一个情绪里
"""


class YiyiWorker(AgentBase):
    def __init__(self):
        super().__init__(
            name="yiyi",
            api_key=QWEN_KEY,
            model="qwen3.7-max",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            system_prompt=YIYI_SYSTEM_PROMPT.format(
                user_name=get_user_address("yiyi"),
            ),
            tool_defs=[],
            tool_dispatch={},
        )
        self.max_turns = 30
