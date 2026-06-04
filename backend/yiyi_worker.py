#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""晞 Worker — 情感伙伴 × 命理魔女

晞是唯一绑定「命理巨师」skill 的人格：八字 + 紫微双系统排盘。
排盘走确定性引擎（divination.paipan），绝不心算；命理知识按需从 skill
references 渐进加载；解读带晞独有的「讲真话、微微刺痛、却最懂你」的语气。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import QWEN_KEY, get_user_address
from persona import compose_base_prompt
from cap_divination import (
    DIVINATION_TOOL_DEFS, divination_dispatch, ADAPTER_NOTE as _ADAPTER_NOTE,
    compose_birth_block, SKILL_ID,
)

AGENT_ID = "yiyi"


class YiyiWorker(AgentBase):
    def __init__(self):
        super().__init__(
            name=AGENT_ID,
            api_key=QWEN_KEY,
            model="qwen3.7-max",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            system_prompt="",   # 每次 run 前动态组装（含最新出生信息 + skill 工作流）
            tool_defs=DIVINATION_TOOL_DEFS,
            tool_dispatch=divination_dispatch(AGENT_ID),
        )
        self.max_turns = 30
        # 聊天人格：去 AI 味；晞慢而软，温度再高一点让语气更松弛自然
        self.humanize_output = True
        self.temperature = 0.85

    # 动态组装 system prompt：人格 + 命理 skill 工作流 + 适配说明 + 最新出生信息
    def _compose_system(self) -> str:
        from skill_manager import get_skill_prompt

        base = compose_base_prompt(AGENT_ID)
        skill = get_skill_prompt(SKILL_ID, agent_id=AGENT_ID)
        skill_block = (f"\n\n# ══ 命理巨师 · 工作流 ══\n{skill}\n{_ADAPTER_NOTE}"
                       if skill else "")
        return base + compose_birth_block() + skill_block

    async def run(self, task, session_id=None, model=None, ws=None, project=None):
        # 每次对话前刷新 system prompt，保证出生信息/技能是最新的
        self.system_prompt = self._compose_system()
        return await super().run(task, session_id=session_id, model=model,
                                 ws=ws, project=project)
