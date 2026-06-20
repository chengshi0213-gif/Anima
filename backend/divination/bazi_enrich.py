#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bazi_enrich.py — 八字结构化增强（格局/旺衰/五行/干支关系/长生）

借鉴 dzcmemory-web/bazi-ziwei-skill 的 enrichment 层思路，
为 interpret.py 提供更丰富的结构化元数据。确定性查表，不依赖 LLM。
"""
from __future__ import annotations

GAN_WUXING = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
              "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
GAN_YANG = {"甲": True, "乙": False, "丙": True, "丁": False, "戊": True,
            "己": False, "庚": True, "辛": False, "壬": True, "癸": False}
ZHI_WUXING = {"子": "水", "丑": "土", "寅": "木", "卯": "木", "辰": "土",
              "巳": "火", "午": "火", "未": "土", "申": "金", "酉": "金",
              "戌": "土", "亥": "水"}
ZHI_ORDER = list("子丑寅卯辰巳午未申酉戌亥")

SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE = {"木": "土", "火": "金", "土": "水", "金": "木", "水": "火"}
BEI_KE = {v: k for k, v in KE.items()}

MONTH_SEASON = {
    "寅": "木", "卯": "木", "巳": "火", "午": "火",
    "申": "金", "酉": "金", "亥": "水", "子": "水",
    "辰": "土", "未": "土", "戌": "土", "丑": "土",
}

WUHE = [("甲", "己", "土"), ("乙", "庚", "金"), ("丙", "辛", "水"),
        ("丁", "壬", "木"), ("戊", "癸", "火")]

LIUCHONG = [("子", "午"), ("丑", "未"), ("寅", "申"), ("卯", "酉"),
            ("辰", "戌"), ("巳", "亥")]

LIUHE = [("子", "丑", "土"), ("寅", "亥", "木"), ("卯", "戌", "火"),
         ("辰", "酉", "金"), ("巳", "申", "水"), ("午", "未", "火")]

SANHE = [("申", "子", "辰", "水"), ("亥", "卯", "未", "木"),
         ("寅", "午", "戌", "火"), ("巳", "酉", "丑", "金")]

XIANGXING = [
    ("寅", "巳", "无恩之刑"), ("巳", "申", "无恩之刑"),
    ("丑", "戌", "恃势之刑"), ("戌", "未", "恃势之刑"), ("未", "丑", "恃势之刑"),
    ("子", "卯", "无礼之刑"),
]
ZIXING = {"辰", "午", "酉", "亥"}

_CS_NAMES = ["长生", "沐浴", "冠带", "临官", "帝旺", "衰", "病", "死", "墓", "绝", "胎", "养"]
_CS_START = {"甲": 11, "丙": 2, "戊": 2, "庚": 5, "壬": 8,
             "乙": 6, "丁": 9, "己": 9, "辛": 0, "癸": 3}

_GEJU_NAMES = {
    "比肩": "建禄格", "劫财": "月刃格",
    "食神": "食神格", "伤官": "伤官格",
    "正财": "正财格", "偏财": "偏财格",
    "正官": "正官格", "七杀": "七杀格",
    "正印": "正印格", "偏印": "偏印格",
}

_POS_ZH = {"year": "年柱", "month": "月柱", "day": "日柱", "time": "时柱"}


def _changsheng(gan: str, zhi: str) -> str:
    if gan not in _CS_START or zhi not in ZHI_ORDER:
        return ""
    zhi_idx = ZHI_ORDER.index(zhi)
    start = _CS_START[gan]
    if gan in ("甲", "丙", "戊", "庚", "壬"):
        offset = (zhi_idx - start) % 12
    else:
        offset = (start - zhi_idx) % 12
    return _CS_NAMES[offset]


def determine_geju(bazi: dict) -> dict:
    pillars = bazi.get("pillars", {})
    month = pillars.get("month", {})
    hide_gan = month.get("hide_gan", [])
    shishen_zhi = month.get("shishen_zhi", [])
    if not hide_gan or not shishen_zhi:
        return {"name": "", "basis": ""}

    other_gans = set()
    for pos in ("year", "time"):
        g = pillars.get(pos, {}).get("gan", "")
        if g:
            other_gans.add(g)

    chosen_idx = 0
    for i, hg in enumerate(hide_gan):
        if hg in other_gans:
            chosen_idx = i
            break

    benqi_ss = shishen_zhi[chosen_idx] if chosen_idx < len(shishen_zhi) else ""
    benqi_gan = hide_gan[chosen_idx] if chosen_idx < len(hide_gan) else ""

    return {
        "name": _GEJU_NAMES.get(benqi_ss, ""),
        "basis": benqi_ss,
        "benqi_gan": benqi_gan,
        "tougan": [pos for pos in ("year", "time")
                   if pillars.get(pos, {}).get("gan") == benqi_gan],
        "special": benqi_ss in ("比肩", "劫财"),
    }


def score_wangshuai(bazi: dict) -> dict:
    dm = bazi.get("day_master", "")
    dm_wx = GAN_WUXING.get(dm, "")
    if not dm_wx:
        return {"level": "未知", "score": 0, "details": []}

    pillars = bazi.get("pillars", {})
    month_zhi = pillars.get("month", {}).get("zhi", "")
    score = 0.0
    details = []

    season_wx = MONTH_SEASON.get(month_zhi, "")
    if season_wx == dm_wx:
        score += 3; details.append("得令(月令同属)")
    elif SHENG.get(season_wx) == dm_wx:
        score += 1.5; details.append("得令(月令生身)")
    elif BEI_KE.get(dm_wx) == season_wx:
        score -= 3; details.append("失令(月令克身)")
    elif dm_wx == SHENG.get(season_wx):
        score -= 1.5; details.append("失令(月令泄身)")
    else:
        details.append("月令中性")

    for pos in ("year", "month", "day", "time"):
        p = pillars.get(pos, {})
        for hg in p.get("hide_gan", []):
            hg_wx = GAN_WUXING.get(hg, "")
            if hg_wx == dm_wx:
                score += 0.8
            elif SHENG.get(hg_wx) == dm_wx:
                score += 0.4

    for pos in ("year", "month", "time"):
        gan_wx = GAN_WUXING.get(pillars.get(pos, {}).get("gan", ""), "")
        if gan_wx == dm_wx:
            score += 1.2
        elif SHENG.get(gan_wx) == dm_wx:
            score += 0.6

    day_hg = pillars.get("day", {}).get("hide_gan", [])
    if any(GAN_WUXING.get(h) == dm_wx for h in day_hg):
        score += 1.0
        details.append("日支通根")

    if score >= 6:
        level = "极旺"
    elif score >= 2.5:
        level = "偏旺"
    elif score >= -1.5:
        level = "中和"
    elif score >= -5:
        level = "偏弱"
    else:
        level = "极弱"

    return {"level": level, "score": round(score, 1), "details": details}


def count_wuxing(bazi: dict) -> dict:
    count = {"木": 0.0, "火": 0.0, "土": 0.0, "金": 0.0, "水": 0.0}
    pillars = bazi.get("pillars", {})
    weights = [1.0, 0.5, 0.3]

    for pos in ("year", "month", "day", "time"):
        p = pillars.get(pos, {})
        wx = GAN_WUXING.get(p.get("gan", ""))
        if wx:
            count[wx] += 1.0
        for i, hg in enumerate(p.get("hide_gan", [])):
            wx = GAN_WUXING.get(hg)
            if wx:
                count[wx] += weights[min(i, 2)]

    count = {k: round(v, 1) for k, v in count.items()}
    return {
        "count": count,
        "missing": [k for k, v in count.items() if v == 0],
        "strongest": max(count, key=count.get),
        "weakest": min(count, key=count.get),
    }


SHISHEN_ORDER = ["比肩", "劫财", "食神", "伤官", "正财",
                 "偏财", "正官", "七杀", "正印", "偏印"]


def shishen_of(dm: str, gan: str) -> str:
    """日主 dm 看天干 gan，得十神名。"""
    a, b = GAN_WUXING.get(dm), GAN_WUXING.get(gan)
    if not a or not b:
        return ""
    same = GAN_YANG.get(dm) == GAN_YANG.get(gan)
    if a == b:
        return "比肩" if same else "劫财"
    if SHENG.get(a) == b:            # 我生 → 食伤
        return "食神" if same else "伤官"
    if KE.get(a) == b:              # 我克 → 财
        return "偏财" if same else "正财"
    if KE.get(b) == a:             # 克我 → 官杀
        return "七杀" if same else "正官"
    if SHENG.get(b) == a:          # 生我 → 印
        return "偏印" if same else "正印"
    return ""


def count_shishen(bazi: dict) -> list[dict]:
    """十神占比：天干(除日主) + 藏干(按位加权) 统计十种十神分布。"""
    dm = bazi.get("day_master", "")
    raw = {k: 0.0 for k in SHISHEN_ORDER}
    pillars = bazi.get("pillars", {})
    weights = [1.0, 0.5, 0.3]
    for pos in ("year", "month", "day", "time"):
        p = pillars.get(pos, {})
        if pos != "day":                       # 日干即日主，不计十神
            ss = shishen_of(dm, p.get("gan", ""))
            if ss in raw:
                raw[ss] += 1.0
        for i, hg in enumerate(p.get("hide_gan", [])):
            ss = shishen_of(dm, hg)
            if ss in raw:
                raw[ss] += weights[min(i, 2)]
    total = sum(raw.values()) or 1.0
    return [{"name": k, "value": round(raw[k], 1),
             "percent": round(raw[k] / total * 100)} for k in SHISHEN_ORDER]


def find_gan_relations(bazi: dict) -> list[dict]:
    pillars = bazi.get("pillars", {})
    gans = [(pos, pillars.get(pos, {}).get("gan", ""))
            for pos in ("year", "month", "day", "time")]

    results = []
    for i in range(len(gans)):
        for j in range(i + 1, len(gans)):
            g1, g2 = gans[i][1], gans[j][1]
            pos1, pos2 = gans[i][0], gans[j][0]
            for a, b, wx in WUHE:
                if {g1, g2} == {a, b}:
                    results.append({
                        "type": "五合", "gans": f"{g1}{g2}",
                        "positions": f"{_POS_ZH[pos1]}·{_POS_ZH[pos2]}",
                        "result": f"合化{wx}",
                    })
    return results


def find_zhi_relations(bazi: dict) -> list[dict]:
    pillars = bazi.get("pillars", {})
    zhis = [(pos, pillars.get(pos, {}).get("zhi", ""))
            for pos in ("year", "month", "day", "time")]

    results = []

    for i in range(len(zhis)):
        for j in range(i + 1, len(zhis)):
            z1, z2 = zhis[i][1], zhis[j][1]
            p1, p2 = zhis[i][0], zhis[j][0]
            lbl = f"{_POS_ZH[p1]}·{_POS_ZH[p2]}"

            for a, b in LIUCHONG:
                if {z1, z2} == {a, b}:
                    results.append({"type": "六冲", "zhis": f"{z1}{z2}", "positions": lbl})

            for a, b, wx in LIUHE:
                if {z1, z2} == {a, b}:
                    results.append({"type": "六合", "zhis": f"{z1}{z2}",
                                    "positions": lbl, "result": f"合化{wx}"})

            for a, b, desc in XIANGXING:
                if (z1 == a and z2 == b) or (z1 == b and z2 == a):
                    results.append({"type": "相刑", "zhis": f"{z1}{z2}",
                                    "positions": lbl, "desc": desc})

    zhi_set = {z[1] for z in zhis}
    for a, b, c, wx in SANHE:
        present = {x for x in (a, b, c) if x in zhi_set}
        if len(present) == 3:
            results.append({"type": "三合", "zhis": f"{a}{b}{c}", "result": f"合{wx}局"})
        elif len(present) == 2:
            results.append({"type": "半合", "zhis": "".join(sorted(present)),
                            "result": f"半合{wx}"})

    zhi_counts: dict[str, int] = {}
    for _, z in zhis:
        zhi_counts[z] = zhi_counts.get(z, 0) + 1
    for z, cnt in zhi_counts.items():
        if z in ZIXING and cnt >= 2:
            results.append({"type": "自刑", "zhis": f"{z}{z}"})

    return results


def changsheng_states(bazi: dict) -> dict:
    dm = bazi.get("day_master", "")
    pillars = bazi.get("pillars", {})
    states = {}
    for pos in ("year", "month", "day", "time"):
        zhi = pillars.get(pos, {}).get("zhi", "")
        if dm and zhi:
            states[pos] = _changsheng(dm, zhi)
    return states


def enrich_bazi(bazi: dict) -> dict:
    if not bazi or not bazi.get("day_master"):
        return {}
    return {
        "geju": determine_geju(bazi),
        "wangshuai": score_wangshuai(bazi),
        "wuxing": count_wuxing(bazi),
        "gan_relations": find_gan_relations(bazi),
        "zhi_relations": find_zhi_relations(bazi),
        "changsheng": changsheng_states(bazi),
    }
