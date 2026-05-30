#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
orchestrator.py — 陶朱编排层（M6 + M8）

陶朱（CEO）通过 delegate(role, task) 把有边界的子任务派给子员工：
  executor 执行者/工程师 · writer 写手 · reader 阅读者 · critic 评审
  researcher 研究员 · analyst 数据分析师 · product_manager 产品经理
子员工各自跑独立的 ReAct 循环，完成后把摘要交还陶朱。

设计要点：
  - 子员工懒加载（importlib，首次 delegate 才实例化），避免模块级循环 import；
    陶朱 import 本模块时不触发任何 worker 实例化。
  - delegate 是同步工具回调（AgentBase._execute_tool 同步调用），
    而子员工 run() 是 async：在**独立线程**里 asyncio.run 跑，主线程 join 等结果。
    这与现有阻塞型工具（shell_run/web_search）行为一致，不与服务器主事件循环冲突。

M8：受控递归编排（仅技术负责人型子员工可再派活）。
  - 深度上限 _MAX_DEPTH=2：陶朱(0)→executor(1)→子executor/critic(2)，再往下拒绝。
  - 全树派活预算 _MAX_TREE_DELEGATIONS：单次顶层任务内总派活次数封顶，防成本失控。
  - 默认子员工**无 delegate**；只有显式 allowed_roles 的"负责人"才挂受限 delegate。
"""
from __future__ import annotations

import asyncio
import importlib
import threading
from typing import Optional

# role → (模块名, 类名, 给陶朱看的能力描述)
SUBAGENT_FACTORIES: dict[str, tuple[str, str, str]] = {
    "executor": ("executor_worker", "ExecutorWorker",
                 "执行者/工程师：代码编写修改、文件操作、shell、测试驱动开发——接到明确任务自规划+自验证地交付"),
    "writer":   ("writer_worker", "WriterWorker",
                 "写手：商业文案、技术文档、产品方案、创意内容——高质量文字交付"),
    "reader":   ("reader_worker", "ReaderWorker",
                 "阅读者：长文/代码库/研究报告的定位、深读、分层摘要——信息提取"),
    "critic":   ("critic_worker", "CriticWorker",
                 "评审：代码评审、方案评估、逻辑检查、风险识别——专挑问题，不来夸的"),
    "researcher": ("researcher_worker", "ResearcherWorker",
                   "研究员：联网检索、竞品/市场调研、资料搜集与交叉验证——Tavily 检索+网页抓取后给带来源的结论"),
    "analyst":  ("analyst_worker", "AnalystWorker",
                 "数据分析师：财务建模、数据处理、算账测算——跑 Python 出数字、图表数据与结论"),
    "product_manager": ("pm_worker", "ProductManagerWorker",
                        "产品经理：需求拆解、产品方案、排期里程碑、任务清单——把模糊目标变成可执行的 PRD 与计划"),
}

# 受控递归参数
_MAX_DEPTH = 2                 # 编排树最大深度（陶朱=0）
_MAX_TREE_DELEGATIONS = 16     # 单次顶层任务内总派活次数上限（防递归/扇出失控）

# 子员工实例缓存（懒加载，进程内复用）
_instances: dict[str, object] = {}

# 每条派活链的上下文（depth + 全树共享计数）存在 threading.local，
# 在子员工运行的那个线程里设置，从而让其内部的 delegate 能读到当前深度。
_local = threading.local()


def _get_ctx() -> Optional[dict]:
    return getattr(_local, "ctx", None)


def _get_subagent(role: str):
    """懒加载并缓存子员工实例。"""
    if role not in _instances:
        mod_name, cls_name, _ = SUBAGENT_FACTORIES[role]
        module = importlib.import_module(mod_name)
        _instances[role] = getattr(module, cls_name)()
    return _instances[role]


def list_subagents() -> dict:
    """列出可调度的子员工及其能力（供陶朱决策派给谁）。"""
    return {
        "subagents": [
            {"role": role, "description": desc}
            for role, (_, _, desc) in SUBAGENT_FACTORIES.items()
        ]
    }


def delegate(role: str, task: str,
             context: str = "", model: Optional[str] = None,
             allowed_roles: Optional[set[str]] = None,
             project: Optional[str] = None) -> dict:
    """
    把子任务派给指定子员工，阻塞等其跑完，返回 {role,status,summary,files_changed,turns}。

    role:          executor/writer/reader/critic/researcher/analyst/product_manager
    task:          交给子员工的具体任务描述
    context:       可选背景信息（避免子员工重复探索）
    model:         可选模型显示名覆盖
    allowed_roles: 受限派活白名单（负责人型子员工用；None=陶朱，可派全部）
    project:       项目名（M9 项目级记忆）。不传则沿派活链继承父级项目，
                   再不行回退到当前活跃项目——让整棵编排树共享同一份项目上下文。
    """
    role = (role or "").strip().lower()
    if role not in SUBAGENT_FACTORIES:
        return {"error": f"未知子员工: {role!r}，可选: {list(SUBAGENT_FACTORIES)}"}
    if allowed_roles is not None and role not in allowed_roles:
        return {"error": f"你无权把任务派给 {role!r}，可派: {sorted(allowed_roles)}"}
    if not task or not task.strip():
        return {"error": "task 不能为空"}

    # ── 受控递归护栏 ──
    ctx = _get_ctx()
    if ctx is None:
        shared = {"count": 0, "max": _MAX_TREE_DELEGATIONS, "lock": threading.Lock()}
        depth = 0
    else:
        shared = ctx["shared"]
        depth = ctx["depth"]

    # ── 项目级记忆：解析本次派活归属的项目（M9 Part 2）──
    #   显式 project > 沿链继承父级 project > 当前活跃项目 > 无
    if project is None:
        project = (ctx or {}).get("project")
    if project is None:
        try:
            from memory_injector import get_active_project
            project = get_active_project()
        except Exception:
            project = None
    if depth >= _MAX_DEPTH:
        return {"error": f"已达最大编排深度 {_MAX_DEPTH}，不能再向下派活（防递归失控）"}
    with shared["lock"]:
        if shared["count"] >= shared["max"]:
            return {"error": f"已达单次任务派活上限 {shared['max']} 次（防成本失控）"}
        shared["count"] += 1

    full_task = task if not context.strip() else f"## 背景\n{context}\n\n## 任务\n{task}"

    try:
        agent = _get_subagent(role)
    except Exception as e:
        return {"error": f"子员工 {role} 实例化失败: {e}"}

    # 在独立线程里跑子员工的 async ReAct 循环；新线程内设置本链上下文（depth+1，
    # 共享同一个 count 对象），使该子员工内部若再 delegate 能正确判深度/扣预算。
    child_ctx = {"shared": shared, "depth": depth + 1, "project": project}
    box: dict = {}

    def _runner():
        _local.ctx = child_ctx
        try:
            box["result"] = asyncio.run(
                agent.run(full_task, model=model, project=project))
        except Exception as e:  # noqa: BLE001
            box["result"] = {"status": "error", "error": str(e)}

    t = threading.Thread(target=_runner, name=f"subagent-{role}", daemon=True)
    t.start()
    t.join()

    res = box.get("result") or {"status": "error", "error": "子员工无返回"}
    return {
        "role":          role,
        "status":        res.get("status"),
        "summary":       res.get("summary", res.get("error", "")),
        "files_changed": res.get("files_changed", []),
        "turns":         res.get("turn_count"),
    }


# ── 共享工具定义 / dispatch ──────────────────────────────────────────

DELEGATE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "delegate",
        "description": "把一个有明确边界的子任务派给子员工去做（你擅长拆解与调度，"
                       "脏活累活交给专员）。子员工会独立完成并把摘要交还给你。"
                       "先想清楚派给谁、任务边界是什么，再调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": list(SUBAGENT_FACTORIES.keys()),
                    "description": "子员工角色：executor(执行/写代码)/writer(写作)/reader(阅读分析)/"
                                   "critic(评审)/researcher(联网调研)/analyst(数据测算)/product_manager(需求与排期)",
                },
                "task":    {"type": "string", "description": "交给子员工的具体任务描述（边界清晰）"},
                "context": {"type": "string", "description": "可选：你已掌握的背景，帮子员工少走弯路"},
            },
            "required": ["role", "task"],
        },
    },
}

LIST_SUBAGENTS_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "list_subagents",
        "description": "列出你手下可调度的子员工及各自擅长什么（决定派给谁之前先看看）。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

ORCHESTRATION_TOOL_DEFS = [DELEGATE_TOOL_DEF, LIST_SUBAGENTS_TOOL_DEF]


def build_orchestration_dispatch(allowed_roles: Optional[set[str]] = None) -> dict:
    """返回 {tool_name: callable} 供 worker 合并进 tool_dispatch。

    allowed_roles=None：陶朱，可派全部子员工。
    allowed_roles={...}：负责人型子员工（如 executor），只能派白名单内角色。
    """
    return {
        "delegate":       lambda **kw: delegate(
            kw["role"], kw["task"], kw.get("context", ""), kw.get("model"),
            allowed_roles=allowed_roles),
        "list_subagents": lambda **kw: list_subagents(),
    }


def lead_delegate_tool_defs(allowed_roles: set[str]) -> list[dict]:
    """负责人型子员工的受限 delegate 工具定义（enum 只列白名单角色）。"""
    d = {
        "type": "function",
        "function": {
            "name": "delegate",
            "description": "把可以并行/隔离的子任务派给下属专员（你是负责人，能拆活）。"
                           "受深度与预算限制，只在确有必要时用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": sorted(allowed_roles),
                             "description": "下属角色"},
                    "task": {"type": "string", "description": "具体子任务（边界清晰）"},
                    "context": {"type": "string", "description": "可选背景"},
                },
                "required": ["role", "task"],
            },
        },
    }
    return [d]
