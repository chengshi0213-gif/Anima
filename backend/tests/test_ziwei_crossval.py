#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ziwei_crossval.py — 紫微排盘 多命例交叉验证 (pytest matrix)

差分测试: Anima 运行时用 iztro-py(纯 Python 移植), 此 golden 用真 iztro-JS(社区标准库本体,
不同实现)预先生成 (tests/ziwei_golden.json, 60 命例覆盖全部五行局/全部命宫地支), 离线逐例逐宫对账。
既验适配层映射, 又验 iztro-py 与 iztro-JS 的移植一致性(含年界补丁)。

对账口径 = 各派系高共识的确定性核心字段:
    五行局 / 命宫干支 / 身宫 / 紫微·天府落宫 / 12宫宫干 / 12宫主星 / 大限起运岁。

为何存在: 紫微排盘错一步(如五行局)则全盘错, 单命例测试曾长期"假绿"放过线上 bug;
另 iztro-py 端口有年界 bug(立春 vs 正月初一), 由 ziwei_engine 运行时补丁修正, 此处兜底回归。
详见 memory anima-divination-audit。

重生 golden (需 Node + 一次性装 iztro):
    cd tests/tools && npm init -y && npm install iztro
    node generate_ziwei_golden.js 60 ../ziwei_golden.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from divination import paipan  # noqa: E402

_GOLDEN_PATH = Path(__file__).parent / "ziwei_golden.json"

MAIN_STARS = {"紫微", "天机", "太阳", "武曲", "天同", "廉贞", "天府",
              "太阴", "贪狼", "巨门", "天相", "天梁", "七杀", "破军"}


def _load_golden() -> dict:
    if not _GOLDEN_PATH.exists():
        pytest.skip(f"golden 快照缺失: {_GOLDEN_PATH} (运行 generate_golden.js 生成)")
    return json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))


_GOLDEN = _load_golden()
_CASES = _GOLDEN.get("cases", [])


def _birth_dict(b: dict) -> dict:
    return {
        "date": f"{b['year']:04d}-{b['month']:02d}-{b['day']:02d}",
        "time": f"{b['hour']:02d}:{b['minute']:02d}",
        "gender": b["gender"],
    }


def _case_id(case: dict) -> str:
    b = case["birth"]
    return f"{b['year']}-{b['month']:02d}-{b['day']:02d}_{b['hour']:02d}h_{b['gender'][0]}"


def _diff_case(case: dict) -> list[str]:
    """跑 Anima 排盘, 与参照 golden 逐项比对, 返回不一致项列表 (空=通过)。"""
    birth = _birth_dict(case["birth"])
    ref = case["ref"]
    zw = paipan(birth)["ziwei"]
    diffs: list[str] = []

    # ── 全局核心 ──
    if zw["wuxing_ju"] != ref["wuXingJu"]:
        diffs.append(f"五行局: anima={zw['wuxing_ju']} ref={ref['wuXingJu']}")
    if zw["ming_gong"]["ganzhi"] != ref["mingGanzhi"]:
        diffs.append(f"命宫干支: anima={zw['ming_gong']['ganzhi']} ref={ref['mingGanzhi']}")
    if zw["shen_gong"]["branch"] != ref["shenBranch"]:
        diffs.append(f"身宫: anima={zw['shen_gong']['branch']} ref={ref['shenBranch']}")
    if zw["ziwei_branch"] != ref["ziweiBranch"]:
        diffs.append(f"紫微位: anima={zw['ziwei_branch']} ref={ref['ziweiBranch']}")
    if zw["tianfu_branch"] != ref["tianfuBranch"]:
        diffs.append(f"天府位: anima={zw['tianfu_branch']} ref={ref['tianfuBranch']}")

    # ── 逐宫: 宫干 / 主星 ──
    pal_by_branch = {p["branch"]: p for p in zw["palaces"]}
    for branch, rb in ref["byBranch"].items():
        p = pal_by_branch.get(branch)
        if p is None:
            diffs.append(f"[{branch}] 宫缺失")
            continue
        if p["ganzhi"][0] != rb["tiangan"]:
            diffs.append(f"[{branch}]宫干: anima={p['ganzhi'][0]} ref={rb['tiangan']}")
        anima_main = sorted(s["name"] for s in p["stars"] if s["name"] in MAIN_STARS)
        ref_main = sorted(rb["main"])
        if anima_main != ref_main:
            diffs.append(f"[{branch}]主星: anima={anima_main} ref={ref_main}")

    # ── 大限起运岁 (按地支对齐) ──
    dx_by_branch = {d["branch"]: d["age_range"][0] for d in zw["daxian"]}
    for branch, rb in ref["byBranch"].items():
        if rb.get("startAge") is None:
            continue
        a = dx_by_branch.get(branch)
        if a != rb["startAge"]:
            diffs.append(f"[{branch}]大限起运: anima={a} ref={rb['startAge']}")

    return diffs


@pytest.mark.parametrize("case", _CASES, ids=[_case_id(c) for c in _CASES])
def test_ziwei_matches_reference(case):
    diffs = _diff_case(case)
    assert not diffs, "\n  ".join([f"{_case_id(case)} 与参照不一致:"] + diffs)


def test_golden_coverage():
    """golden 必须覆盖全部 5 个五行局 + 全部 12 命宫地支, 否则 harness 形同虚设。"""
    jus = {c["ref"]["wuXingJu"] for c in _CASES}
    mings = {c["ref"]["mingBranch"] for c in _CASES}
    assert jus == {"水二局", "木三局", "金四局", "土五局", "火六局"}, f"五行局覆盖不全: {jus}"
    assert len(mings) == 12, f"命宫地支覆盖不全({len(mings)}/12): {sorted(mings)}"
    assert len(_CASES) >= 50, f"命例过少: {len(_CASES)}"
