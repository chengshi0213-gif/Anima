#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_interpret.py — 命盘解读引擎测试

锁三件事：
1. 解读底本 interpret_data.py（蒸馏自 minglijushi/references 古籍语料）结构完整。
2. interpret_chart 按命盘事实查表，产出非空且对得上盘的解读（含四化落宫这种强约束项）。
3. bazi_enrich 算法层产出正确的结构化元数据。
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from divination import paipan, interpret_chart            # noqa: E402
from divination import interpret_data as D                 # noqa: E402
from divination.bazi_enrich import enrich_bazi             # noqa: E402

_BIRTH = {"date": "2002-02-24", "time": "07:30", "gender": "male"}
_PALACES = {"命宫", "兄弟", "夫妻", "子女", "财帛", "疾厄",
            "迁移", "交友", "官禄", "田宅", "福德", "父母"}


def test_data_completeness():
    assert len(D.MAIN_STAR) == 14
    assert len(D.DAY_MASTER) == 10
    assert len(D.SHISHEN) == 10
    assert len(D.TIAOHOU) == 12
    assert set(D.SIHUA_MEANING) == {"化禄", "化权", "化科", "化忌"}
    for hua in ("化禄", "化权", "化科", "化忌"):
        assert set(D.SIHUA_IN_PALACE[hua]) == _PALACES, f"{hua} 入宫不全"
    # 主星每项字段齐
    for st, v in D.MAIN_STAR.items():
        assert {"core", "person", "merit", "flaw", "career"} <= set(v), st


def test_data_v2_tables():
    """v2 新增底本表结构完整。"""
    assert len(D.GEJU_DESC) == 10
    for name, v in D.GEJU_DESC.items():
        assert {"summary", "detail", "like", "dislike"} <= set(v), name
    assert len(D.WANGSHUAI_DESC) == 5
    assert len(D.CHANGSHENG_DESC) == 12
    assert len(D.ZHI_RELATION_DESC) >= 6
    assert len(D.PILLAR_DOMAIN) == 4
    assert len(D.PALACE_AXIS) == 3
    # DAY_MASTER v2 是 dict-of-dict
    for dm, v in D.DAY_MASTER.items():
        assert isinstance(v, dict), f"DAY_MASTER[{dm}] should be dict"
        assert {"nature", "character", "relationship", "advice"} <= set(v), dm
    # SHISHEN v2 有 detail 字段
    for ss, v in D.SHISHEN.items():
        assert "detail" in v, f"SHISHEN[{ss}] missing 'detail'"
    # MAIN_STAR v2 有 in_ming 字段
    for st, v in D.MAIN_STAR.items():
        assert "in_ming" in v, f"MAIN_STAR[{st}] missing 'in_ming'"


def test_interpret_chart_user():
    chart = paipan(_BIRTH)
    I = interpret_chart(chart)
    assert I["bazi"] and I["ziwei"]
    # 八字：日主癸 出现
    titles_b = " ".join(s["title"] for s in I["bazi"])
    assert "癸" in titles_b
    # 紫微：命宫武曲（用户盘 命宫庚戌武曲化忌）
    z_titles = " ".join(s["title"] for s in I["ziwei"])
    assert "武曲" in z_titles
    # 生年四化落宫：恰好 4 条，且化忌落命宫（武曲化忌坐命）
    sihua = next((s for s in I["ziwei"] if "四化" in s["title"]), None)
    assert sihua and len(sihua["items"]) == 4
    assert any("化忌" in x and "命宫" in x for x in sihua["items"]), sihua["items"]


def test_interpret_v2_section_count():
    """v2 应产出更多解读段落。"""
    chart = paipan(_BIRTH)
    I = interpret_chart(chart)
    assert len(I["bazi"]) >= 6, f"bazi only {len(I['bazi'])} sections"
    assert len(I["ziwei"]) >= 6, f"ziwei only {len(I['ziwei'])} sections"


def test_interpret_v2_bazi_sections():
    """v2 八字应包含格局/旺衰/四柱/五行/干支关系等新段落。"""
    chart = paipan(_BIRTH)
    I = interpret_chart(chart)
    titles = " ".join(s["title"] for s in I["bazi"])
    assert "格局" in titles, "missing 格局 section"
    assert "旺衰" in titles, "missing 旺衰 section"
    assert "四柱" in titles, "missing 四柱概览 section"
    assert "五行" in titles, "missing 五行 section"
    assert "调候" in titles, "missing 调候 section"


def test_interpret_v2_ziwei_sections():
    """v2 紫微应包含多轴分析。"""
    chart = paipan(_BIRTH)
    I = interpret_chart(chart)
    titles = " ".join(s["title"] for s in I["ziwei"])
    assert "事业主轴" in titles, "missing 事业主轴"
    assert "人际" in titles, "missing 人际关系"
    assert "生活底色" in titles, "missing 生活底色"
    assert "身宫" in titles, "missing 身宫"


def test_interpret_v2_dayun_reading():
    """大运不再是裸列表：有引子 body + 逐运 items（含十神运/喜忌/主题）。"""
    chart = paipan(_BIRTH)
    I = interpret_chart(chart)
    dy = next((s for s in I["bazi"] if "大运" in s["title"]), None)
    assert dy is not None, "缺大运段落"
    assert dy.get("body"), "大运缺引子 body"
    items = dy.get("items", [])
    assert len(items) >= 8, f"大运逐运过少：{len(items)}"
    for it in items:
        assert "运" in it                                   # 标了十神运
        assert ("喜" in it or "忌" in it or "平" in it)      # 标了喜忌
    # 当前所在大运被点名（命主 2002 生，今年必在某步运中）
    assert "你正走这一步" in "".join(items) or "正走" in dy["body"]


def test_interpret_deterministic():
    chart = paipan(_BIRTH)
    assert interpret_chart(chart) == interpret_chart(chart)


def test_interpret_no_crash_on_minimal():
    """缺时辰也不崩，仍出解读。"""
    I = interpret_chart(paipan({"date": "1988-08-08", "gender": "female"}))
    assert isinstance(I["bazi"], list) and isinstance(I["ziwei"], list)
    assert len(I["bazi"]) >= 4


# ── bazi_enrich 算法层测试 ──────────────────────────────────

def test_enrich_bazi_structure():
    """enrich_bazi 返回六大板块。"""
    chart = paipan(_BIRTH)
    e = enrich_bazi(chart["bazi"])
    assert "geju" in e
    assert "wangshuai" in e
    assert "wuxing" in e
    assert "gan_relations" in e
    assert "zhi_relations" in e
    assert "changsheng" in e


def test_enrich_geju():
    chart = paipan(_BIRTH)
    geju = enrich_bazi(chart["bazi"])["geju"]
    assert geju.get("name"), "格局 name should not be empty"
    assert geju.get("basis"), "格局 basis should not be empty"


def test_enrich_wangshuai():
    chart = paipan(_BIRTH)
    ws = enrich_bazi(chart["bazi"])["wangshuai"]
    assert ws["level"] in ("极旺", "偏旺", "中和", "偏弱", "极弱")
    assert isinstance(ws["score"], (int, float))


def test_enrich_wuxing():
    chart = paipan(_BIRTH)
    wx = enrich_bazi(chart["bazi"])["wuxing"]
    assert set(wx["count"].keys()) == {"木", "火", "土", "金", "水"}
    assert isinstance(wx["missing"], list)
    assert wx["strongest"] in ("木", "火", "土", "金", "水")


def test_enrich_changsheng():
    chart = paipan(_BIRTH)
    cs = enrich_bazi(chart["bazi"])["changsheng"]
    assert "day" in cs
    valid_stages = {"长生", "沐浴", "冠带", "临官", "帝旺", "衰", "病", "死", "墓", "绝", "胎", "养"}
    for pos, stage in cs.items():
        assert stage in valid_stages, f"{pos}: {stage} not valid"


def test_enrich_empty_input():
    assert enrich_bazi({}) == {}
    assert enrich_bazi({"day_master": ""}) == {}
