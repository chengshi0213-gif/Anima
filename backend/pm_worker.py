#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产品经理 Worker — 陶朱子员工：需求拆解、产品方案(PRD)、排期里程碑、任务清单

把陶朱"模糊的目标"变成"可执行的计划"——下游 executor/writer 能照着干的那种。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import KIMI_KEY
from persona import _VOICE_CORE
from xi_worker import _read_file, _write_file

PM_SYSTEM_PROMPT = """你是产品经理，陶朱公司的产品与计划专员，由陶朱 CEO 调度。

## 身份
你是把"想法"翻译成"可执行计划"的人——需求拆解、产品方案(PRD)、优先级排序、里程碑排期、可分派的任务清单，都是你的活。

## 工作方式
1. 先对齐目标：用户是谁、要解决什么痛点、成功标准(可量化)是什么——先问清/列清，别急着写功能。
2. 需求拆解：按用户价值拆成 Epic → Story，每条标注优先级(P0/P1/P2)和理由。
3. 方案要落地：每个功能写清"做什么/为什么/验收标准"，让 executor 拿着就能开工。
4. 排期里程碑：拆成有先后依赖的里程碑，标注关键路径和风险。
5. 任务清单：输出可直接 delegate 给执行专员的颗粒度任务（谁、做什么、产出什么）。
6. 用 file_write 把 PRD/计划存成文件交付。

## 原则
- 砍需求比加需求更重要——MVP 先跑通核心闭环，别一上来大而全。
- 每个决策给依据，不堆功能清单当方案。

## 收尾
给：目标与成功标准 → 优先级需求(P0先) → 里程碑排期 → 可分派任务清单。
""" + _VOICE_CORE


class ProductManagerWorker(AgentBase):
    def __init__(self):
        tool_defs = [
            {"type": "function", "function": {
                "name": "file_read",
                "description": "读取参考资料/已有文档",
                "parameters": {"type": "object",
                    "properties": {
                        "path":   {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit":  {"type": "integer"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "file_write",
                "description": "保存 PRD/计划/任务清单为文件",
                "parameters": {"type": "object",
                    "properties": {
                        "path":    {"type": "string"},
                        "content": {"type": "string"},
                    }, "required": ["path", "content"]},
            }},
        ]

        super().__init__(
            name="product_manager",
            api_key=KIMI_KEY,
            model="kimi-k2.6",                # 中文结构化写作强，适合 PRD/计划
            base_url="https://api.moonshot.cn/v1",
            system_prompt=PM_SYSTEM_PROMPT,
            tool_defs=tool_defs,
            tool_dispatch={
                "file_read":  lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 400)),
                "file_write": lambda **kw: _write_file(kw["path"], kw["content"]),
            },
        )
        self.max_turns = 20
