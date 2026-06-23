#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_weight.py — 记忆权重模型（留存权重）

把"该不该长期留"(留存权重) 和 "这轮该不该调出来"(检索权重) 拆成两件事。
本模块只管**留存权重**，纯函数、无副作用、不依赖 DB / embedding，便于单测与复用。

留存权重的脊梁是"删除代价 / 不可重得性"，不是"重要性"：
  你随口说的私事删了就真没了(高留存)；能从对话随时重算的事丢了也长得回来(低留存)。

合成（机械底座，天天能跑，不烧 token）：
  留存权重 = 来源分 × 按类衰减 × (1 + 复现增益)，clamp 到 [0,1]
用户已拍板：**偏来源**——来源分主导，复现只作加成、且封顶。

设计稿见 docs/memory-weight-and-curator-plan.md。
"""
from __future__ import annotations

import math
import time
from typing import Optional

# ── 按类半衰期（天）。身份/关系近乎不衰减，近期状态快衰减 ────────────
HALFLIFE_BY_CATEGORY: dict[str, float] = {
    # 身份恒定 / 关系记忆 / 用户画像：你是谁、你们之间的事 —— 近乎不衰减
    "A": 730.0, "D": 730.0, "user_profile": 730.0,
    # 升格洞察：蒸出来的"你是什么样的人"
    "L2": 540.0,
    # 偏好习惯：你怎么干活、口味 —— 慢衰减，被印证就刷新
    "B": 90.0, "preference": 90.0, "writing_style": 90.0,
    # 近期状态：这阵子忙啥、什么情绪 —— 快衰减，到期主动重判
    "C": 14.0,
}
# 其余分类（note/general/business/knowledge/...）的兜底半衰期。
# 取 30 与历史全局 RECENCY_HALFLIFE_DAYS 一致，保证未分级记忆行为不变。
DEFAULT_HALFLIFE = 30.0

# ── 来源分（脊梁 = 不可重得性）：由 category 给基线，source 微调 ──────
# 你主动说/纠正/承诺(A/D) > 她观察推断(L2/B) > 系统客套一次性(C/其它)
SOURCE_BASE_BY_CATEGORY: dict[str, float] = {
    "A": 1.0, "D": 1.0,            # 删了就真没了
    "user_profile": 0.9,
    "L2": 0.8,                      # 重得回但代价高
    "B": 0.7, "preference": 0.7, "writing_style": 0.7,
    "C": 0.4,                       # 多半能从对话重算
}
DEFAULT_SOURCE_BASE = 0.5

# source 字段里这些渠道标记，意味着"你亲口/亲手留下"，对不可重得性加成
_FIRSTHAND_SOURCE_HINTS = ("desktop", "user", "correction", "promise")
_FIRSTHAND_BONUS = 0.1

# ── 复现增益：每多一条独立印证 +RECUR_GAIN，封顶 RECUR_CAP ───────────
# 偏来源：复现最多把权重抬 RECUR_CAP，盖不过来源分的主导地位。
RECUR_GAIN = 0.15
RECUR_CAP = 0.6

_TS_FMT = "%Y-%m-%dT%H:%M:%S"


def halflife_for(category: Optional[str]) -> float:
    """该分类的衰减半衰期（天）。未知分类回退 DEFAULT_HALFLIFE。"""
    return HALFLIFE_BY_CATEGORY.get(category or "", DEFAULT_HALFLIFE)


def _parse_ts(ts: Optional[str]) -> Optional[float]:
    if not ts:
        return None
    try:
        return time.mktime(time.strptime(ts, _TS_FMT))
    except (ValueError, TypeError):
        return None


def recency_factor(category: Optional[str],
                   last_ts: Optional[str],
                   now: Optional[float] = None) -> float:
    """按类半衰期的指数衰减，返回 [0,1]。

    last_ts 解析失败 / 缺失时按"刚发生"(1.0) 处理——坏时间戳不该把记忆错误打入冷宫。
    """
    ts = _parse_ts(last_ts)
    if ts is None:
        return 1.0
    now = time.time() if now is None else now
    days = max(0.0, (now - ts) / 86400.0)
    return math.exp(-days / halflife_for(category))


def source_score(category: Optional[str], source: Optional[str] = None) -> float:
    """不可重得性基线（按类）+ 亲手来源加成，clamp [0,1]。"""
    base = SOURCE_BASE_BY_CATEGORY.get(category or "", DEFAULT_SOURCE_BASE)
    if source:
        s = source.lower()
        if any(h in s for h in _FIRSTHAND_SOURCE_HINTS):
            base += _FIRSTHAND_BONUS
    return max(0.0, min(1.0, base))


def recurrence_gain(recurrence: int) -> float:
    """跨对话被独立印证的条数 → 增益系数，封顶 RECUR_CAP。

    recurrence ≤ 1 视为无加成（本身那一条不算印证）。
    """
    extra = max(0, int(recurrence) - 1)
    return min(RECUR_CAP, extra * RECUR_GAIN)


def retention_weight(category: Optional[str],
                     source: Optional[str] = None,
                     last_reinforced: Optional[str] = None,
                     recurrence: int = 0,
                     now: Optional[float] = None) -> float:
    """留存权重（机械底座）= 来源分 × 按类衰减 × (1 + 复现增益)，clamp [0,1]。

    - last_reinforced：优先用"最后被现实印证"的时间；调用方没有时可传 updated_at。
    - recurrence：跨多次对话对同一事的独立印证条数（由聚簇得出；单条传 0/1）。
    - 偏来源：source_score 是主导乘子，复现只在其上加成、且封顶 RECUR_CAP。
    """
    src = source_score(category, source)
    rec = recency_factor(category, last_reinforced, now)
    gain = 1.0 + recurrence_gain(recurrence)
    return max(0.0, min(1.0, src * rec * gain))


def retention_weight_entry(entry, recurrence: int = 0,
                           now: Optional[float] = None) -> float:
    """便捷重载：直接吃一个 MemoryEntry。

    印证时间取 last_reinforced，缺失时回退 updated_at（向后兼容旧数据）。
    """
    last = getattr(entry, "last_reinforced", None) or getattr(entry, "updated_at", None)
    return retention_weight(
        category=getattr(entry, "category", None),
        source=getattr(entry, "source", None),
        last_reinforced=last,
        recurrence=recurrence,
        now=now,
    )
