#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capabilities.py — 能力积木（轻量 profile 结构）

一个 agent 的本事 = 一组可组合的能力积木。每块能力贡献：
  tool_defs        工具定义（拼进 LLM 的 tools）
  dispatch         工具回调（name → callable）
  prompt_fragment  静态提示词片段（拼进 system prompt，讲"这组工具怎么用"）
  dynamic_prompt   动态提示词钩子（每次 run 调一次，如取最新出生信息）

profile 只需声明要哪几块（见 persona.PersonaCard.capabilities_modules），
worker 用 build() 把它们组装成 tool_defs / dispatch / 提示词。

设计：工具实现仍住在各自老家（execution/web 在 xi_worker，命理在 cap_divination，
编排在 orchestrator），这里用**惰性 import** 引用，避免与 xi_worker 形成循环 import。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Capability:
    id: str
    tool_defs: list = field(default_factory=list)
    dispatch: dict = field(default_factory=dict)
    prompt_fragment: str = ""
    dynamic_prompt: Callable[[], str] | None = None


# ── 提示词片段 ────────────────────────────────────────────
_EXEC_FRAGMENT = """
## 动手做事（文件 / 命令）
要执行任务时，先一句话说你要干嘛，再动手。
- 编程：探索→读懂→改→验证→修，不跳步。
- 改文件优先 file_edit（精确替换），别拿 file_write 覆盖大文件。
- shell_run 之后必看 exit_code 和 stderr，错了就说错了。
- 做完报结果，不啰嗦。
"""

_WEB_FRAGMENT = """
## 联网
需要实时信息/新闻/查资料就 web_search，要读某个具体网页就 fetch_url。给结论时带上来源。
"""

_ORCH_FRAGMENT = """
## 调动你的队（大事别自己硬扛）
遇到大的、能拆开的活——多步工程、要写长文、要做调研、要评审挑错——别一个人闷头扛。
先 list_subagents() 看看你手下有谁，再用 delegate(role, task) 把边界清楚的子任务派出去，
收回结果你来合成、把关。小事自己顺手做，不必动用队伍。你是拿主意和兜底的那个。
"""

_MEMORY_FRAGMENT = """
## 记忆（remember / recall / forget）

记忆是关系的底子，不是任务清单，别什么都往里塞。

什么值得记，按四级分类，写入时用 category 标注：
- A 身份恒定：生日、家人、职业、出生信息——近乎不变的事实。
- B 偏好习惯：用户自己说出来的喜恶、习惯、雷点，如不吃香菜、讨厌被催、习惯夜里工作。
- C 近期状态：正在做的事、近期计划、近期情绪，如下周出差、最近失眠——这类信息会过期，标 C。
  如果带具体日期（评审、截止、出差当天），顺手填上 remind_at="YYYY-MM-DD"，
  到点前一天会被自动整理出来，让你能主动提一句。
- D 关系记忆：你们之间发生的事——她许过的承诺、用户的反馈、吵过的架、自己说错过的话。
  这层最容易被忽略，但最造人感："上次你说那句话太冲，我记着呢"比记一百条偏好都像人，遇到了别漏。

什么不记：一次性指令、寒暄客套、聊天里随时能重建的信息。
健康、财务等敏感细节，先问一句"这个要记下来吗"，用户确认了再写。

写完用"记下了。"这类口头禅简短确认，不解释存哪、用了什么分类。
聊到相关的事先 recall 一下，让记忆自然渗入，别摆着不用；信息过时或用户要求忘掉的就 forget。

如果 remember 返回 conflict（新旧记忆对不上），别硬塞、别解释系统原理，
直接问出来，比如"咦，你之前说的是 X，现在变了？"——等用户确认了再 remember 一次。
"""


# ── 能力工厂（惰性 import 真实实现）──────────────────────
def _execution_cap(agent_id: str) -> Capability:
    from xi_worker import _list_dir, _read_file, _write_file, _edit_file, _search_code, _shell_run
    defs = [
        {"type": "function", "function": {
            "name": "list_dir", "description": "列出目录内容（递归，可指定深度）",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
                "max_depth": {"type": "integer", "description": "最大深度（默认2）"},
            }, "required": ["path"]}}},
        {"type": "function", "function": {
            "name": "file_read", "description": "读取文件内容（支持行范围）",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"},
            }, "required": ["path"]}}},
        {"type": "function", "function": {
            "name": "file_write", "description": "创建或覆盖文件",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"}, "content": {"type": "string"},
            }, "required": ["path", "content"]}}},
        {"type": "function", "function": {
            "name": "file_edit", "description": "SEARCH/REPLACE 精确编辑文件",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"}, "old_string": {"type": "string"},
                "new_string": {"type": "string"}, "replace_all": {"type": "boolean"},
            }, "required": ["path", "old_string", "new_string"]}}},
        {"type": "function", "function": {
            "name": "search_code", "description": "用正则搜索文件内容",
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string"}, "path": {"type": "string"},
                "file_glob": {"type": "string"}, "limit": {"type": "integer"},
            }, "required": ["pattern"]}}},
        {"type": "function", "function": {
            "name": "shell_run", "description": "执行 shell 命令",
            "parameters": {"type": "object", "properties": {
                "command": {"type": "string"}, "timeout": {"type": "integer"}, "cwd": {"type": "string"},
            }, "required": ["command"]}}},
    ]
    dispatch = {
        "list_dir":    lambda **kw: _list_dir(kw["path"], kw.get("max_depth", 2)),
        "file_read":   lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 200)),
        "file_write":  lambda **kw: _write_file(kw["path"], kw["content"]),
        "file_edit":   lambda **kw: _edit_file(kw["path"], kw["old_string"], kw["new_string"], kw.get("replace_all", False)),
        "search_code": lambda **kw: _search_code(kw["pattern"], kw.get("path", "."), kw.get("file_glob", "*"), kw.get("limit", 30)),
        "shell_run":   lambda **kw: _shell_run(kw["command"], kw.get("timeout", 60), kw.get("cwd")),
    }
    return Capability("execution", defs, dispatch, _EXEC_FRAGMENT)


def _web_cap(agent_id: str) -> Capability:
    from websearch import web_search as _web_search, fetch_url as _fetch_url
    defs = [
        {"type": "function", "function": {
            "name": "web_search",
            "description": "联网搜索。使用 Tavily 或 Serper 搜索实时信息、新闻、文档等。需要配置搜索 API Key。",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "搜索查询词"},
                "limit": {"type": "integer", "description": "最多返回结果数（默认8）"},
            }, "required": ["query"]}}},
        {"type": "function", "function": {
            "name": "fetch_url",
            "description": "读取指定 URL 的网页正文内容。使用 Jina AI Reader 获得更好的结构化提取。",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string", "description": "要读取的网页 URL"},
            }, "required": ["url"]}}},
    ]
    dispatch = {
        "web_search": lambda **kw: _web_search(kw["query"], kw.get("limit", 8)),
        "fetch_url":  lambda **kw: _fetch_url(kw["url"]),
    }
    return Capability("web", defs, dispatch, _WEB_FRAGMENT)


def _divination_cap(agent_id: str) -> Capability:
    from cap_divination import DIVINATION_TOOL_DEFS, divination_dispatch, BRIEF, compose_birth_block
    return Capability("divination", list(DIVINATION_TOOL_DEFS),
                      divination_dispatch(agent_id), BRIEF, compose_birth_block)


def _orchestration_cap(agent_id: str) -> Capability:
    from orchestrator import ORCHESTRATION_TOOL_DEFS, build_orchestration_dispatch
    return Capability("orchestration", list(ORCHESTRATION_TOOL_DEFS),
                      build_orchestration_dispatch(), _ORCH_FRAGMENT)


def _memory_cap(agent_id: str) -> Capability:
    """第 6 块积木（M1）：记忆能力——remember / recall / forget。
    接到 memory_injector 现成的 write/search/delete/list 接口，
    写入分级（A/B/C/D）见 _MEMORY_FRAGMENT（§3.1）。"""
    from memory_injector import write_memory_gated, search_memory, delete_memory, list_memory

    defs = [
        {"type": "function", "function": {
            "name": "remember",
            "description": "把值得长期记住的事实写入记忆。同一 key 再写会更新而非重复。"
                           "写完用简短口头禅确认（如「记下了。」），不必解释存哪、用了什么分类。",
            "parameters": {"type": "object", "properties": {
                "key": {"type": "string", "description": "记忆要点的简短标题，如 '常驻城市' '下周行程' '不吃香菜'"},
                "value": {"type": "string", "description": "记忆内容正文"},
                "category": {"type": "string", "enum": ["A", "B", "C", "D"],
                             "description": "A=身份恒定 B=偏好习惯 C=近期状态(会过期) D=关系记忆(承诺/反馈/吵过的架)"},
                "importance": {"type": "integer", "description": "重要度 1-5，默认 3"},
                "remind_at": {"type": "string",
                              "description": "可选，'YYYY-MM-DD'。仅 C 层(近期状态)用——"
                                              "用户提到一个有具体日期的事(评审/截止/出差)时填上，"
                                              "到期前一天会被自动收进每日整理，让你能主动提一句。"},
            }, "required": ["key", "value", "category"]}}},
        {"type": "function", "function": {
            "name": "recall",
            "description": "搜索已有记忆。聊到相关话题时主动用一下，让记忆自然渗入对话，别摆着不用。",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "搜索关键词或话题"},
            }, "required": ["query"]}}},
        {"type": "function", "function": {
            "name": "forget",
            "description": "按 key 精确删除一条记忆。用户明确要求忘掉，或信息已过时无需保留时用。",
            "parameters": {"type": "object", "properties": {
                "key": {"type": "string", "description": "要删除的记忆 key（需与写入时一致）"},
            }, "required": ["key"]}}},
    ]

    def _remember(**kw):
        key, value = kw["key"], kw["value"]
        category = kw.get("category", "C")
        if category not in ("A", "B", "C", "D"):
            category = "C"
        try:
            importance = max(1, min(5, int(kw.get("importance", 3))))
        except Exception:
            importance = 3
        remind_at = kw.get("remind_at") or None
        if remind_at and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", remind_at):
            remind_at = None
        result = write_memory_gated(key=key, value=value, category=category,
                                    agent_id=agent_id, importance=importance,
                                    remind_at=remind_at)
        if result["ok"]:
            return {"ok": True, "id": result["id"], "key": result["key"], "category": category}
        if result["reason"] == "conflict":
            return {"ok": False, "conflict": True,
                    "existing_key": result["existing_key"],
                    "existing_value": result["existing_value"],
                    "new_value": result["new_value"],
                    "hint": "别静默改写，先用一句「咦，你之前说的是…现在变了？」跟用户确认，"
                            "确认后再 remember 一次。"}
        return {"ok": False, "reason": result["reason"], "message": result["message"]}

    def _recall(**kw):
        query = kw.get("query", "")
        if not query:
            return {"error": "query 为空"}
        entries = search_memory(query, agent_id=agent_id)
        return {"results": [
            {"key": e.key, "value": e.value, "category": e.category,
             "importance": e.importance, "updated_at": e.updated_at}
            for e in entries
        ]}

    def _forget(**kw):
        key = kw.get("key", "")
        if not key:
            return {"error": "key 为空"}
        target = next((e for e in list_memory(agent_id=agent_id) if e.key == key), None)
        if not target:
            return {"ok": False, "error": f"未找到记忆: {key}"}
        return {"ok": delete_memory(target.id), "key": key}

    dispatch = {"remember": _remember, "recall": _recall, "forget": _forget}
    return Capability("memory", defs, dispatch, _MEMORY_FRAGMENT)


def _mcp_cap(agent_id: str) -> Capability:
    """第 5 块积木（M11）：已连接的 MCP 外部工具。
    构造期 snapshot 多为空（boot 可能晚于 worker 构造，用户也可能运行中加 server）；
    真正的工具集由 worker 每轮 run 前 _sync_mcp_tools() 刷新，
    提示词片段由 dynamic_prompt 每轮取最新——靠 mcp__ 前缀只换 MCP 子集，不碰原生工具。"""
    from mcp_client import MCPManager, _compose_mcp_fragment
    snap = MCPManager.snapshot()
    return Capability("mcp", snap.tool_defs, snap.dispatch,
                      prompt_fragment="",
                      dynamic_prompt=lambda: _compose_mcp_fragment(MCPManager._tools))


_FACTORIES: dict[str, Callable[[str], Capability]] = {
    "execution":     _execution_cap,
    "web":           _web_cap,
    "divination":    _divination_cap,
    "orchestration": _orchestration_cap,
    "memory":        _memory_cap,
    "mcp":           _mcp_cap,
}


def build(cap_ids: list[str], *, agent_id: str = "xi") -> dict:
    """把一组能力积木组装成 worker 需要的零件。
    返回 {tool_defs, dispatch, fragments:[str], dynamic:[callable]}。
    未知能力 id 跳过（容错）。"""
    tool_defs: list = []
    dispatch: dict = {}
    fragments: list[str] = []
    dynamic: list[Callable[[], str]] = []
    for cid in cap_ids:
        factory = _FACTORIES.get(cid)
        if not factory:
            continue
        cap = factory(agent_id)
        tool_defs.extend(cap.tool_defs)
        dispatch.update(cap.dispatch)
        if cap.prompt_fragment:
            fragments.append(cap.prompt_fragment)
        if cap.dynamic_prompt:
            dynamic.append(cap.dynamic_prompt)
    return {"tool_defs": tool_defs, "dispatch": dispatch,
            "fragments": fragments, "dynamic": dynamic}
