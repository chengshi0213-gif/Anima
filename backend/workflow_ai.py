#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workflow_ai.py — AI 结构化搭建工作流（M10 Part 1）

把"用户一句话目标"编译成一张**显式、可编辑、可重复**的工作流图——
这正是"更多由 AI 搭建"的正解：AI 负责生成可编辑的产物，而不是每次黑盒重跑。

与旧版 `wfAiGenerate`（前端劫持聊天 WS、只能吐扁平顺序步骤、正则硬抠 JSON）相比：
  - 服务端结构化生成，提示词覆盖**全部节点类型**（顺序/并行/条件/循环），AI 真能搭富结构。
  - 鲁棒解析：剥 ```json``` 围栏、抠首个 JSON、坏 JSON 不致命。
  - 校验：agent 合法性（非法→纠正为 xi 并告警）、节点结构补全、空 prompt 告警。
  - 支持**对话式编辑**：传入现有 steps + 修改指令，AI 改图而非重搭。
  - 返回 {name, steps, explanation, variables, warnings}，前端可预览/填变量/再改。

本模块不依赖具体 worker，只要传入一个有 `async _call_api(messages, tools=None, stream=False)`
的 generator（任意 AgentBase 子类实例都行；tools=None 时不会触发 ReAct/delegate）。
"""
from __future__ import annotations

import json
import re
from typing import Optional

# 工作流里可调度的 agent → 能力简介（喂给规划器，让它知道派给谁）
# 4 个核心人格 + 陶朱花名册 7 子员工。
try:
    from orchestrator import SUBAGENT_FACTORIES as _SUB
    _ORCH = {r: d for r, (_, _, d) in _SUB.items()}
except Exception:
    _ORCH = {}

KNOWN_AGENTS: dict[str, str] = {
    "xi":       "Anima（私人助理/通才）：日常对话、检索、轻量整理、统筹——拿不准派谁就用它",
    "yiyi":     "晞（命理顾问）：八字/紫微排盘、命理解读",
    "tianyuan": "陶朱（CEO/编排）：把模糊目标拆成计划、统筹多专员",
    "shoucang": "守藏（谏臣/记忆）：复盘、谏言、长期记忆沉淀",
    **_ORCH,
}

_ALLOWED_TYPES = {"sequential", "parallel", "condition", "loop"}

_PLANNER_SYSTEM = """你是工作流架构师。把用户的目标编译成一张可执行的工作流图，用 JSON 返回。

## 可调度的员工（agent 字段只能取这些 id）
{agents}

## 节点类型与 JSON 结构
顺序（默认）：{{"type":"sequential","agent":"<id>","prompt":"给该员工的具体指令","pass_context":true}}
并行：       {{"type":"parallel","branches":[{{"agent":"<id>","prompt":"...","pass_context":true}}, ...]}}
条件：       {{"type":"condition","keyword":"触发词","true_step":{{"agent":"<id>","prompt":"..."}},"false_step":{{"agent":"<id>","prompt":"..."}}}}
循环：       {{"type":"loop","max_iter":3,"stop_keyword":"完成","step":{{"agent":"<id>","prompt":"...","pass_context":true}}}}

## 规则
- pass_context=true 表示把上一步的产出喂给这一步（默认就该 true，除非这一步是全新起点）。
- 用户输入里需要运行时填的占位用 {{{{变量名}}}}（双花括号）表示，例如 {{{{主题}}}}。
- 选对员工：调研用 researcher、写作用 writer、评审/把关用 critic、算数据用 analyst、写代码用 executor、需求排期用 product_manager。
- 步骤数量克制：能 3-5 步说清就别堆十几步。能并行的别串行。

## 输出格式（严格）
只返回一个 JSON 对象，不要任何解释文字、不要 markdown 围栏：
{{"name":"给这条工作流起个简短名字","steps":[ ...节点数组... ],"explanation":"两三句话说明这条流在干嘛、为什么这么编排"}}
"""

_EDIT_SUFFIX = """

## 这是修改请求
下面是当前已有的工作流 steps（JSON）。请在它的基础上按用户的新指令**修改**，保留没被要求改动的部分，返回完整的新 JSON 对象（同上格式）。
当前 steps：
{current}
"""


def _planner_messages(description: str, current_steps: Optional[list]) -> list[dict]:
    agents_doc = "\n".join(f"- {aid}：{desc}" for aid, desc in KNOWN_AGENTS.items())
    sys = _PLANNER_SYSTEM.format(agents=agents_doc)
    if current_steps:
        sys += _EDIT_SUFFIX.format(current=json.dumps(current_steps, ensure_ascii=False))
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": f"用户目标：{description}"},
    ]


def _extract_json(text: str) -> Optional[dict | list]:
    """从模型输出里尽量抠出 JSON 对象/数组。容忍 ```json``` 围栏与前后废话。"""
    if not text:
        return None
    t = text.strip()
    # 剥 markdown 围栏
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if fence:
        t = fence.group(1).strip()
    # 先整体试
    try:
        return json.loads(t)
    except Exception:
        pass
    # 抠第一个 { ... } 或 [ ... ]（贪婪到最后一个闭合）
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i, j = t.find(open_c), t.rfind(close_c)
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except Exception:
                continue
    return None


def _norm_leaf(step: dict, warnings: list[str]) -> dict:
    """规整一个"叶子"步骤（含 agent/prompt/pass_context）。"""
    agent = (step.get("agent") or "xi").strip()
    if agent not in KNOWN_AGENTS:
        warnings.append(f"未知 agent '{agent}'，已改用 xi")
        agent = "xi"
    out = {
        "agent": agent,
        "prompt": (step.get("prompt") or "").strip(),
        "pass_context": step.get("pass_context", True) is not False,
    }
    if not out["prompt"]:
        warnings.append(f"{agent} 的某步 prompt 为空")
    return out


def _normalize(parsed: dict | list, warnings: list[str]) -> tuple[str, list, str]:
    """把模型返回的结构规整成 (name, steps, explanation)，并就地校验。"""
    name, explanation = "AI 工作流", ""
    if isinstance(parsed, dict):
        name = (parsed.get("name") or name).strip() or name
        explanation = (parsed.get("explanation") or "").strip()
        raw_steps = parsed.get("steps")
    else:
        raw_steps = parsed
    if not isinstance(raw_steps, list):
        warnings.append("未能解析出 steps 列表")
        return name, [], explanation

    steps: list[dict] = []
    for s in raw_steps:
        if not isinstance(s, dict):
            warnings.append("跳过一个非对象步骤")
            continue
        t = (s.get("type") or "sequential").strip()
        if t not in _ALLOWED_TYPES:
            warnings.append(f"未知节点类型 '{t}'，按 sequential 处理")
            t = "sequential"

        if t == "parallel":
            branches = [_norm_leaf(b, warnings) for b in (s.get("branches") or []) if isinstance(b, dict)]
            if not branches:
                warnings.append("并行节点无有效分支，已跳过")
                continue
            steps.append({"type": "parallel", "branches": branches})
        elif t == "condition":
            node = {"type": "condition", "keyword": (s.get("keyword") or "").strip()}
            if isinstance(s.get("true_step"), dict):
                node["true_step"] = _norm_leaf(s["true_step"], warnings)
            if isinstance(s.get("false_step"), dict):
                node["false_step"] = _norm_leaf(s["false_step"], warnings)
            if "true_step" not in node and "false_step" not in node:
                warnings.append("条件节点缺少分支，已跳过")
                continue
            steps.append(node)
        elif t == "loop":
            inner = s.get("step")
            if not isinstance(inner, dict):
                warnings.append("循环节点缺少 step，已跳过")
                continue
            steps.append({
                "type": "loop",
                "max_iter": int(s.get("max_iter", 3) or 3),
                "stop_keyword": (s.get("stop_keyword") or "完成").strip(),
                "step": _norm_leaf(inner, warnings),
            })
        else:  # sequential
            leaf = _norm_leaf(s, warnings)
            steps.append({"type": "sequential", **leaf})
    return name, steps, explanation


def _iter_prompts(steps: list) -> list[str]:
    out = []
    for s in steps:
        t = s.get("type")
        if t == "parallel":
            out += [b.get("prompt", "") for b in s.get("branches", [])]
        elif t == "condition":
            for k in ("true_step", "false_step"):
                if isinstance(s.get(k), dict):
                    out.append(s[k].get("prompt", ""))
        elif t == "loop":
            if isinstance(s.get("step"), dict):
                out.append(s["step"].get("prompt", ""))
        else:
            out.append(s.get("prompt", ""))
    return out


def detect_variables(steps: list) -> list[str]:
    """扫出所有 {{变量}} 占位（保序去重），供前端跑前填值。"""
    seen, ordered = set(), []
    for p in _iter_prompts(steps):
        for m in re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", p or ""):
            if m not in seen:
                seen.add(m)
                ordered.append(m)
    return ordered


async def ai_build_workflow(generator, description: str,
                            current_steps: Optional[list] = None) -> dict:
    """用 generator 的模型把目标编译成工作流图。

    generator: 任意有 `async _call_api(messages, tools=None, stream=False)` 的对象。
    description: 用户的目标 / 修改指令。
    current_steps: 传了就是"在现有图上改"（对话式编辑）。
    返回: {ok, name, steps, explanation, variables, warnings} 或 {ok:False, error}。
    """
    if not (description or "").strip():
        return {"ok": False, "error": "目标描述为空"}
    messages = _planner_messages(description.strip(), current_steps)
    try:
        resp = await generator._call_api(messages, tools=None, stream=False)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"模型调用失败: {e}"}
    if resp.get("error"):
        return {"ok": False, "error": resp["error"]}

    parsed = _extract_json(resp.get("content", ""))
    if parsed is None:
        return {"ok": False, "error": "模型未返回可解析的工作流 JSON",
                "raw": (resp.get("content") or "")[:500]}

    warnings: list[str] = []
    name, steps, explanation = _normalize(parsed, warnings)
    if not steps:
        return {"ok": False, "error": "未能从模型输出构造出有效步骤",
                "warnings": warnings, "raw": (resp.get("content") or "")[:500]}
    return {
        "ok": True,
        "name": name,
        "steps": steps,
        "explanation": explanation,
        "variables": detect_variables(steps),
        "warnings": warnings,
    }
