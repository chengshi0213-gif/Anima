#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_divination.py — 命理排盘引擎 单元测试 (pytest)

锁定确定性排盘结果，防止重构静默回归。
基准命例：1995-08-15 06:30 男（公历），已对照渊海子平 / 紫微斗数全书 算表逐项核验。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_divination.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from divination import paipan  # noqa: E402
from divination.render import render_chart_md  # noqa: E402

BIRTH = {"date": "1995-08-15", "time": "06:30", "gender": "male"}


@pytest.fixture(scope="module")
def chart():
    return paipan(BIRTH)


# ── 八字 ──

def test_bazi_four_pillars(chart):
    p = chart["bazi"]["pillars"]
    assert p["year"]["ganzhi"] == "乙亥"
    assert p["month"]["ganzhi"] == "甲申"
    assert p["day"]["ganzhi"] == "戊寅"
    assert p["time"]["ganzhi"] == "乙卯"


def test_bazi_day_master(chart):
    assert chart["bazi"]["day_master"] == "戊"
    assert chart["bazi"]["day_master_wuxing"] == "土"


def test_bazi_hide_gan_month(chart):
    # 月令申藏 庚壬戊
    assert chart["bazi"]["pillars"]["month"]["hide_gan"] == ["庚", "壬", "戊"]


def test_bazi_dayun_male_reverse(chart):
    # 乙亥阴年 + 男 → 逆行：3癸未 13壬午 23辛巳 33庚辰
    dy = [(d["start_age"], d["ganzhi"]) for d in chart["bazi"]["dayun"][:4]]
    assert dy == [(3, "癸未"), (13, "壬午"), (23, "辛巳"), (33, "庚辰")]


# ── 紫微 ──

def test_ziwei_ming_shen(chart):
    zw = chart["ziwei"]
    assert zw["ming_gong"]["ganzhi"] == "辛巳"
    assert zw["shen_gong"]["branch"] == "亥"


def test_ziwei_wuxing_ju(chart):
    assert chart["ziwei"]["wuxing_ju"] == "金四局"


def test_ziwei_zi_fu_position(chart):
    assert chart["ziwei"]["ziwei_branch"] == "午"
    assert chart["ziwei"]["tianfu_branch"] == "戌"


def test_ziwei_sihua_yi_year(chart):
    sh = chart["ziwei"]["sihua"]
    assert sh == {"化禄": "天机", "化权": "天梁", "化科": "紫微", "化忌": "太阴"}


def test_ziwei_fourteen_main_stars_each_once(chart):
    """十四主星必须且仅出现一次。"""
    main = {"紫微", "天机", "太阳", "武曲", "天同", "廉贞",
            "天府", "太阴", "贪狼", "巨门", "天相", "天梁", "七杀", "破军"}
    seen = {}
    for p in chart["ziwei"]["palaces"]:
        for s in p["stars"]:
            if s["name"] in main:
                seen[s["name"]] = seen.get(s["name"], 0) + 1
    assert set(seen) == main
    assert all(v == 1 for v in seen.values())


def test_ziwei_ming_palace_stars(chart):
    ming = next(p for p in chart["ziwei"]["palaces"] if p["name"] == "命宫")
    names = {s["name"] for s in ming["stars"]}
    assert "天机" in names  # 天机在巳=命宫
    tianji = next(s for s in ming["stars"] if s["name"] == "天机")
    assert "化禄" in tianji["sihua"]


# ── 性别 / 未知时辰 / 农历 ──

def test_ziwei_daxian_gender_flip():
    male = paipan(BIRTH)["ziwei"]["daxian"]
    female = paipan({**BIRTH, "gender": "female"})["ziwei"]["daxian"]
    # 阴男逆行：巳辰卯 ；阴女顺行：巳午未
    assert [d["branch"] for d in male[:3]] == ["巳", "辰", "卯"]
    assert [d["branch"] for d in female[:3]] == ["巳", "午", "未"]


def test_time_unknown_flag():
    c = paipan({"date": "1995-08-15", "gender": "male"})
    assert c["input"]["time_unknown"] is True
    assert c["bazi"]["time_unknown"] is True


def test_lunar_input_equiv_solar():
    # 农历 1995-07-20 == 公历 1995-08-15
    cl = paipan({"date": "1995-07-20", "time": "06:30",
                 "gender": "male", "calendar": "lunar"})
    assert cl["bazi"]["pillars"]["year"]["ganzhi"] == "乙亥"
    assert cl["bazi"]["pillars"]["day"]["ganzhi"] == "戊寅"


# ── 渲染 ──

def test_render_markdown_smoke(chart):
    md = render_chart_md(chart)
    assert "八字命盘" in md and "紫微命盘" in md
    assert "金四局" in md
    assert "| 天干 |" in md  # 四柱表头存在
