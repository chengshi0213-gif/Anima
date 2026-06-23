#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_memory_weight.py — 留存权重模型单元测试

覆盖：
  - 按类半衰期 halflife_for（身份久、近期短、未知回退）
  - 来源分 source_score（A/D 最高、C 最低、亲手来源加成、clamp）
  - 复现增益 recurrence_gain（≤1 无加成、线性、封顶）
  - recency_factor 按类衰减（同龄下近期状态衰减快于身份）
  - retention_weight 合成 + clamp[0,1]
  - **偏来源不变式**：满复现的近期状态仍盖不过零复现的身份记忆
  - retention_weight_entry 优先 last_reinforced，回退 updated_at

运行:
    cd E:\\AI\\workspace\\Anima\\backend
    python -m pytest tests/test_memory_weight.py -v
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import memory_weight as mw  # noqa: E402
from memory_backend import MemoryEntry  # noqa: E402

_FMT = "%Y-%m-%dT%H:%M:%S"
_NOW = time.time()


def _ago(days: float) -> str:
    """days 天前的时间戳字符串。"""
    return time.strftime(_FMT, time.localtime(_NOW - days * 86400))


# ── 按类半衰期 ──────────────────────────────────────────────────

def test_halflife_identity_long_recent_short():
    assert mw.halflife_for("A") == 730.0
    assert mw.halflife_for("D") == 730.0
    assert mw.halflife_for("C") == 14.0
    assert mw.halflife_for("B") == 90.0


def test_halflife_unknown_falls_back_to_default():
    assert mw.halflife_for("general") == mw.DEFAULT_HALFLIFE
    assert mw.halflife_for(None) == mw.DEFAULT_HALFLIFE
    assert mw.halflife_for("没这个分类") == mw.DEFAULT_HALFLIFE


# ── 来源分（不可重得性脊梁）─────────────────────────────────────

def test_source_score_identity_highest_recent_lowest():
    assert mw.source_score("A") == 1.0
    assert mw.source_score("D") == 1.0
    assert mw.source_score("C") < mw.source_score("B") < mw.source_score("A")


def test_source_score_firsthand_bonus_and_clamp():
    # C 基线 0.4 + 亲手加成 0.1 = 0.5
    assert mw.source_score("C", "desktop:work") == 0.5
    # A 已是 1.0，加成后仍 clamp 到 1.0
    assert mw.source_score("A", "user") == 1.0
    # 无 firsthand 命中不加成
    assert mw.source_score("C", "feishu") == 0.4


def test_source_score_unknown_category_default():
    assert mw.source_score("note") == mw.DEFAULT_SOURCE_BASE


# ── 复现增益 ────────────────────────────────────────────────────

def test_recurrence_gain_none_linear_capped():
    assert mw.recurrence_gain(0) == 0.0
    assert mw.recurrence_gain(1) == 0.0           # 本身那条不算印证
    assert mw.recurrence_gain(2) == mw.RECUR_GAIN  # 多一条印证
    assert mw.recurrence_gain(100) == mw.RECUR_CAP  # 封顶


# ── recency_factor 按类衰减 ─────────────────────────────────────

def test_recency_fresh_is_one():
    assert mw.recency_factor("A", _ago(0), now=_NOW) > 0.99


def test_recency_missing_ts_treated_as_fresh():
    assert mw.recency_factor("C", None, now=_NOW) == 1.0
    assert mw.recency_factor("C", "坏时间戳", now=_NOW) == 1.0


def test_recent_decays_faster_than_identity_same_age():
    # 同样 30 天，近期状态(C,半衰期14)衰减得比身份(A,半衰期730)狠得多
    c = mw.recency_factor("C", _ago(30), now=_NOW)
    a = mw.recency_factor("A", _ago(30), now=_NOW)
    assert c < a
    assert c < 0.3       # C 过了两个多半衰期
    assert a > 0.95      # A 几乎没动


# ── retention_weight 合成 + clamp ───────────────────────────────

def test_retention_clamped_to_unit_interval():
    # A 满复现：1.0 × 1.0 × (1+0.6) = 1.6 → clamp 1.0
    w = mw.retention_weight("A", source="user", last_reinforced=_ago(0),
                            recurrence=100, now=_NOW)
    assert w == 1.0


def test_retention_fresh_identity_beats_fresh_recent():
    a = mw.retention_weight("A", last_reinforced=_ago(0), now=_NOW)
    c = mw.retention_weight("C", last_reinforced=_ago(0), now=_NOW)
    assert a > c


def test_bias_toward_source_invariant():
    """偏来源：满复现 + 新鲜的近期状态，仍盖不过零复现 + 新鲜的身份记忆。"""
    recent_max = mw.retention_weight("C", last_reinforced=_ago(0),
                                     recurrence=100, now=_NOW)
    identity_plain = mw.retention_weight("A", last_reinforced=_ago(0),
                                         recurrence=0, now=_NOW)
    assert identity_plain > recent_max


def test_retention_decays_with_age():
    fresh = mw.retention_weight("C", last_reinforced=_ago(0), now=_NOW)
    stale = mw.retention_weight("C", last_reinforced=_ago(60), now=_NOW)
    assert fresh > stale


# ── retention_weight_entry 取时间字段 ───────────────────────────

def test_entry_prefers_last_reinforced_over_updated_at():
    # last_reinforced 新、updated_at 旧 → 应判为新鲜（用 last_reinforced）
    entry = MemoryEntry(
        id="t1", agent_id="xi", category="C", key="k", value="v",
        importance=3, created_at=_ago(60), updated_at=_ago(60),
        last_reinforced=_ago(0),
    )
    w = mw.retention_weight_entry(entry, now=_NOW)
    fresh = mw.retention_weight("C", last_reinforced=_ago(0), now=_NOW)
    assert abs(w - fresh) < 1e-6


def test_entry_falls_back_to_updated_at_when_no_reinforced():
    entry = MemoryEntry(
        id="t2", agent_id="xi", category="C", key="k", value="v",
        importance=3, created_at=_ago(60), updated_at=_ago(60),
        last_reinforced=None,
    )
    w = mw.retention_weight_entry(entry, now=_NOW)
    stale = mw.retention_weight("C", last_reinforced=_ago(60), now=_NOW)
    assert abs(w - stale) < 1e-6
