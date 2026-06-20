#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ziwei_properties.py — 紫微排盘 属性测试 (Hypothesis)

差分对账(test_ziwei_crossval)验"算得对不对"，属性测试验"结构永远自洽"：
对随机生成的命例断言任何命盘都必须成立的不变式，覆盖 golden 命例够不到的输入空间，
专抓适配层映射错误（漏星/串宫/大限错位/四化缺项等）。

运行: python -m pytest tests/test_ziwei_properties.py -q
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from hypothesis import given, settings, example, strategies as st

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from divination import paipan  # noqa: E402

GAN = set("甲乙丙丁戊己庚辛壬癸")
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
ZHI_SET = set(ZHI)
PALACE_NAMES = {"命宫", "兄弟", "夫妻", "子女", "财帛", "疾厄",
                "迁移", "交友", "官禄", "田宅", "福德", "父母"}
MAIN_STARS = {"紫微", "天机", "太阳", "武曲", "天同", "廉贞", "天府",
              "太阴", "贪狼", "巨门", "天相", "天梁", "七杀", "破军"}
JU_NUMS = {"水二局": 2, "木三局": 3, "金四局": 4, "土五局": 5, "火六局": 6}
SIHUA_KEYS = {"化禄", "化权", "化科", "化忌"}


def _assert_invariants(zw: dict, tag: str) -> None:
    pal = zw["palaces"]
    # ── 十二宫：齐、名唯一、地支齐 ──
    assert len(pal) == 12, f"{tag} 宫数≠12"
    assert {p["name"] for p in pal} == PALACE_NAMES, f"{tag} 宫名集错"
    assert {p["branch"] for p in pal} == ZHI_SET, f"{tag} 十二地支未铺满"

    # ── 每宫：干支自洽 ──
    for p in pal:
        gz = p["ganzhi"]
        assert len(gz) == 2 and gz[0] in GAN and gz[1] in ZHI_SET, f"{tag} 宫干支非法 {gz}"
        assert gz[1] == p["branch"], f"{tag} ganzhi 与 branch 不符 {gz}/{p['branch']}"
        assert p["branch_index"] == ZHI.index(p["branch"]), f"{tag} branch_index 错"
        for s in p["stars"]:
            assert isinstance(s["name"], str) and s["name"], f"{tag} 空星名"
            for t in s["sihua"]:
                assert t in SIHUA_KEYS, f"{tag} 非法四化标签 {t}"

    # ── 十四主星：各且仅一次 ──
    seen = [s["name"] for p in pal for s in p["stars"] if s["name"] in MAIN_STARS]
    assert sorted(seen) == sorted(MAIN_STARS), f"{tag} 十四主星非恰好各一次: {sorted(seen)}"

    # ── 五行局 ──
    ju = zw["wuxing_ju"]
    assert ju in JU_NUMS, f"{tag} 五行局非法 {ju}"
    assert zw["ju_number"] == JU_NUMS[ju], f"{tag} ju_number 与名不符"

    # ── 紫微/天府落宫：确实在该宫 ──
    for star, branch in (("紫微", zw["ziwei_branch"]), ("天府", zw["tianfu_branch"])):
        assert branch in ZHI_SET, f"{tag} {star}位非法 {branch}"
        host = next(p for p in pal if p["branch"] == branch)
        assert any(s["name"] == star for s in host["stars"]), f"{tag} {star}不在标称宫 {branch}"

    # ── 生年四化：四项齐、值非空 ──
    assert set(zw["sihua"]) == SIHUA_KEYS, f"{tag} 四化键缺失"
    assert all(v for v in zw["sihua"].values()), f"{tag} 四化有空值: {zw['sihua']}"

    # ── 身宫：唯一且与 shen_gong 一致 ──
    shen = [p for p in pal if p["is_shen_gong"]]
    assert len(shen) >= 1, f"{tag} 无身宫"
    assert zw["shen_gong"]["branch"] in {p["branch"] for p in shen}, f"{tag} 身宫不一致"

    # ── 命宫一致 ──
    ming = next(p for p in pal if p["name"] == "命宫")
    assert zw["ming_gong"]["branch"] == ming["branch"], f"{tag} 命宫支不一致"
    assert zw["ming_gong"]["ganzhi"] == ming["ganzhi"], f"{tag} 命宫干支不一致"

    # ── 大限：12 段、起运岁=局数+10k、各段 10 年、地支齐 ──
    dx = zw["daxian"]
    assert len(dx) == 12, f"{tag} 大限段数≠12"
    starts = sorted(d["age_range"][0] for d in dx)
    expected = sorted(zw["ju_number"] + 10 * k for k in range(12))
    assert starts == expected, f"{tag} 大限起运岁列错: {starts} ≠ {expected}"
    for d in dx:
        assert d["age_range"][1] == d["age_range"][0] + 9, f"{tag} 大限非10年段"
    assert {d["branch"] for d in dx} == ZHI_SET, f"{tag} 大限地支未铺满"

    # ── 杂项 ──
    assert isinstance(zw["time_unknown"], bool)


@settings(max_examples=250, deadline=None)
@given(
    d=st.dates(min_value=date(1920, 2, 5), max_value=date(2080, 12, 31)),
    hour=st.integers(min_value=0, max_value=23),
    gender=st.sampled_from(["male", "female"]),
)
@example(d=date(1996, 2, 12), hour=1, gender="male")    # 立春~农历新年边界(年界补丁回归)
@example(d=date(2002, 2, 24), hour=7, gender="male")    # 用户本人盘
@example(d=date(1966, 5, 11), hour=6, gender="male")    # 闰三月
def test_ziwei_structure_invariants(d, hour, gender):
    birth = {"date": d.isoformat(), "time": f"{hour:02d}:30", "gender": gender}
    zw = paipan(birth)["ziwei"]
    _assert_invariants(zw, birth["date"] + f" {hour}h {gender}")


def test_ziwei_time_unknown_still_valid():
    """缺时辰也必须产出结构自洽的命盘（按午时近似）。"""
    zw = paipan({"date": "1988-08-08", "gender": "female"})["ziwei"]
    _assert_invariants(zw, "time-unknown")
    assert zw["time_unknown"] is True
