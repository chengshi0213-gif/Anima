#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_daily_fortune.py — 今日运势（黄历 + 塔罗 + 个人化提点）测试

锁三件事：
1. 黄历 almanac 取自 lunar-python，结构完整且关键值与权威一致（固定日期回归）。
2. 塔罗牌库 78 张完整、schema 严格；每日一抽按"人+日期"确定性（同入参恒等）。
3. daily_fortune 结构自洽；十神映射正确；个人化提点确定可复现。
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from divination.almanac import today_almanac           # noqa: E402
from divination.tarot import daily_tarot                # noqa: E402
from divination.tarot_deck import TAROT_DECK            # noqa: E402
from divination.daily import daily_fortune, _shishen    # noqa: E402

_BIRTH = {"date": "2002-02-24", "time": "07:30", "gender": "male"}
_D = date(2026, 6, 18)   # 固定日期：丙午年 甲午月 癸亥日


# ── 黄历 ──────────────────────────────────────────────────
def test_almanac_structure_and_known_values():
    a = today_almanac(_D)
    for k in ("solar", "lunar_date", "ganzhi", "overall", "yi", "ji",
              "chong", "tian_shen", "zhixing", "xiu", "jieqi"):
        assert k in a, f"缺字段 {k}"
    assert a["solar"] == "2026-06-18"
    assert a["ganzhi"]["day"] == "癸亥"        # 权威黄历日柱
    assert a["day_shengxiao"] == "猪"
    assert a["zhixing"] == "执"
    assert a["tian_shen"] == {"name": "朱雀", "type": "黑道", "luck": "凶"}
    assert 1 <= a["overall"]["level"] <= 5
    assert a["overall"]["tone"] in ("good", "neutral", "bad")
    assert isinstance(a["yi"], list) and isinstance(a["ji"], list)
    assert a["chong"]["shengxiao"] == "蛇"      # 癸亥日冲丁巳蛇


def test_almanac_deterministic():
    assert today_almanac(_D) == today_almanac(_D)


# ── 塔罗牌库 ──────────────────────────────────────────────
def test_deck_integrity():
    assert len(TAROT_DECK) == 78
    assert [c["id"] for c in TAROT_DECK] == list(range(78))
    need = {"id", "name_en", "name_zh", "arcana", "suit", "rank",
            "upright_keywords", "reversed_keywords", "upright", "reversed"}
    majors = [c for c in TAROT_DECK if c["arcana"] == "major"]
    minors = [c for c in TAROT_DECK if c["arcana"] == "minor"]
    assert len(majors) == 22 and len(minors) == 56
    suits: dict[str, int] = {}
    for c in TAROT_DECK:
        assert set(c) == need, f"#{c['id']} 键集合不符"
        assert c["upright"] and c["reversed"], f"#{c['id']} 解读空"
        assert c["upright_keywords"] and c["reversed_keywords"]
        if c["arcana"] == "minor":
            suits[c["suit"]] = suits.get(c["suit"], 0) + 1
    assert sorted(suits) == ["圣杯", "宝剑", "星币", "权杖"]
    assert all(v == 14 for v in suits.values())


def test_tarot_daily_deterministic_and_valid():
    a = daily_tarot(_BIRTH, _D)
    b = daily_tarot(_BIRTH, _D)
    assert a == b, "同一人同一天必须抽到同一张同一正逆"
    assert 0 <= a["id"] <= 77
    assert a["orientation"] in ("upright", "reversed")
    assert a["name_zh"] and a["meaning"] and a["keywords"]
    # 关键词/解读须与正逆位一致
    card = TAROT_DECK[a["id"]]
    if a["orientation"] == "upright":
        assert a["meaning"] == card["upright"]
    else:
        assert a["meaning"] == card["reversed"]


def test_tarot_varies_by_person_and_day():
    base = daily_tarot(_BIRTH, _D)
    other_person = daily_tarot({"date": "1990-01-01", "gender": "female"}, _D)
    # 不强求不同（理论可能撞），但 (牌, 正逆) 元组在不同人/天间应大体分散：抽若干天看多样性
    seen = {(daily_tarot(_BIRTH, date(2026, 6, d))["id"],
             daily_tarot(_BIRTH, date(2026, 6, d))["orientation"]) for d in range(1, 29)}
    assert len(seen) >= 10, f"28 天里牌面多样性过低: {len(seen)}"
    assert isinstance(other_person["id"], int)


# ── 十神映射 ──────────────────────────────────────────────
@pytest.mark.parametrize("dm,target,expect", [
    ("甲", "甲", "比肩"), ("甲", "乙", "劫财"), ("甲", "丙", "食神"),
    ("甲", "丁", "伤官"), ("甲", "戊", "偏财"), ("甲", "己", "正财"),
    ("甲", "庚", "七杀"), ("甲", "辛", "正官"), ("甲", "壬", "偏印"),
    ("甲", "癸", "正印"),
])
def test_shishen(dm, target, expect):
    assert _shishen(dm, target) == expect


# ── 今日运势整合 ──────────────────────────────────────────
def test_daily_fortune_structure():
    f = daily_fortune(_BIRTH, _D)
    assert set(f) >= {"date", "greeting", "almanac", "tarot", "personal"}
    assert f["date"] == "2026-06-18"
    assert f["personal"]["available"] is True
    assert f["personal"]["shengxiao"] == "马"      # 命主壬午年 → 午马
    # 命主日主 癸；今日日干 癸 → 比肩
    assert f["personal"]["today_shishen"] == "比肩"
    assert isinstance(f["personal"]["tips"], list) and f["personal"]["tips"]


def test_daily_fortune_deterministic():
    assert daily_fortune(_BIRTH, _D) == daily_fortune(_BIRTH, _D)


def test_daily_fortune_no_birth_still_valid():
    """无出生信息：通用黄历 + 塔罗仍出，个人化降级。"""
    f = daily_fortune(None, _D)
    assert f["almanac"]["ganzhi"]["day"] == "癸亥"
    assert f["tarot"]["name_zh"]
    assert f["personal"]["available"] is False
    # 无命盘 → 分项/幸运物降级为空
    assert f["aspects"] == [] and f["lucky"] == {}


# ── 今日分项运程 + 幸运物（测测式四维）──────────────────────
def test_daily_aspects_structure():
    f = daily_fortune(_BIRTH, _D)
    asp = f["aspects"]
    assert len(asp) == 4
    domains = [a["domain"] for a in asp]
    assert domains == ["事业学业", "财运", "感情人际", "健康情绪"]
    for a in asp:
        assert set(a) >= {"domain", "stars", "focus", "text", "advice"}
        assert 1 <= a["stars"] <= 5
        assert a["text"] and a["advice"]
    # 恰一个领域被今日十神点为「今日主场」
    assert sum(1 for a in asp if a["focus"]) == 1


def test_daily_aspects_focus_matches_shishen():
    """命主癸 + 今日癸亥日（比肩）→ 主场落「感情人际」。"""
    f = daily_fortune(_BIRTH, _D)
    assert f["personal"]["today_shishen"] == "比肩"
    assert f["focus_domain"] == "感情人际"
    focus = next(a for a in f["aspects"] if a["focus"])
    assert focus["domain"] == "感情人际"
    # 命主偏旺，比肩属忌 → 主场倾向 caution，星级被压低
    assert focus["stars"] <= 3


def test_daily_lucky_from_yongshen():
    """幸运物取喜用五行：癸水偏旺 → 泄秀取木 → 青绿/东方/3、8。"""
    f = daily_fortune(_BIRTH, _D)
    lk = f["lucky"]
    assert set(lk) >= {"wuxing", "color", "direction", "numbers"}
    assert lk["wuxing"] == "木"
    assert lk["color"] and lk["direction"] and lk["numbers"]
