#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pref_learning.py — M10 偏好学习管线（第⑦层 E 程序层）

工作房间产出 + 用户反应
  → 采集三类隐式信号（编辑diff / 吐槽 / 采纳）入库（pref_signals）
  → 周级 LLM 按领域分桶从信号里抽 E 程序层偏好规则（pref_rules，标来源、单域≤8条、样本不足不抽）
  → always-on 注入工作房间生成上下文（受 room.py 房间门控，日常房间不注入）

§4.1 升格管线管"她懂你这个人"，本管线管"她懂你要的产出长什么样"——两条成长的腿。
"""
from __future__ import annotations

from memory_injector import get_backend, invalidate_cache

PREF_DOMAINS = ["文案", "代码", "PPT", "命盘解读"]
SIGNAL_TYPES = ("edit", "complaint", "accept")
MIN_SIGNALS_PER_DOMAIN = 5
MAX_RULES_PER_DOMAIN = 8


def record_signal(domain, signal_type, original=None, edited=None,
                   note=None, agent_id=None) -> dict:
    if domain not in PREF_DOMAINS:
        return {"ok": False, "error": f"未知领域：{domain}，可选：{PREF_DOMAINS}"}
    if signal_type not in SIGNAL_TYPES:
        return {"ok": False, "error": f"未知信号类型：{signal_type}"}
    backend = get_backend()
    if not hasattr(backend, "record_pref_signal"):
        return {"ok": False, "error": "当前记忆后端不支持偏好信号采集"}
    sid = backend.record_pref_signal(domain, signal_type, original, edited, note, agent_id)
    return {"ok": True, "id": sid, "domain": domain, "signal_type": signal_type}


def get_signal_counts(agent_id=None) -> dict[str, int]:
    backend = get_backend()
    if not hasattr(backend, "count_pref_signals_by_domain"):
        return {}
    counts = backend.count_pref_signals_by_domain()
    return {d: counts.get(d, 0) for d in PREF_DOMAINS}


def get_signals(domain, limit=50) -> list[dict]:
    backend = get_backend()
    if not hasattr(backend, "list_pref_signals"):
        return []
    return backend.list_pref_signals(domain=domain, limit=limit)


def write_pref_rule(domain, rule, source_ids=None, agent_id=None, importance=4) -> dict:
    if domain not in PREF_DOMAINS:
        return {"ok": False, "error": f"未知领域：{domain}，可选：{PREF_DOMAINS}"}
    backend = get_backend()
    if not hasattr(backend, "write_pref_rule"):
        return {"ok": False, "error": "当前记忆后端不支持偏好规则写入"}
    result = backend.write_pref_rule(domain, rule.strip(), source_ids, agent_id,
                                      importance, max_per_domain=MAX_RULES_PER_DOMAIN)
    invalidate_cache()
    return result


def get_pref_rules(domain=None) -> list[dict]:
    backend = get_backend()
    if not hasattr(backend, "list_pref_rules"):
        return []
    return backend.list_pref_rules(domain)


def get_pref_rules_injection() -> str:
    """格式化全部领域的 E 程序层规则，供 agent_base.py 在工作房间注入。无规则时返回空串。"""
    rules = get_pref_rules()
    if not rules:
        return ""
    by_domain: dict[str, list[str]] = {}
    for r in rules:
        by_domain.setdefault(r["domain"], []).append(r["rule"])
    parts = []
    for domain in PREF_DOMAINS:
        domain_rules = by_domain.get(domain)
        if not domain_rules:
            continue
        lines = "\n".join(f"- {r}" for r in domain_rules)
        parts.append(f"[{domain}]\n{lines}")
    if not parts:
        return ""
    return (
        "\n\n## 交付物偏好（从你过去的修改习惯里学到的，仅在对应领域适用）\n"
        + "\n\n".join(parts)
    )


def get_work_room_injection(agent_name: str) -> str:
    """供 agent_base.py 调用：仅当 agent_name 在工作房间生产产出（xi/executor）
    且当前处于工作房间（room.is_work_room()）时，返回 E 程序层规则注入文本；
    否则返回空串。"""
    import room
    if agent_name not in ("xi", "executor"):
        return ""
    if not room.is_work_room():
        return ""
    return get_pref_rules_injection()
