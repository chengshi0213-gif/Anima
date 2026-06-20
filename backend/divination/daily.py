#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily.py — 今日运势（今日黄历 + 今日塔罗 + 结合命盘的个人化提点）

口径（用户拍板）：
- 黄历宜忌吉凶是客观历法，人人相同（almanac.py，权威）。
- 个人化只落在低风险处：命主【日主天干】与今日【日干】的十神关系，
  以及黄历【所冲生肖】是否冲到命主【本命生肖】。给一句留有余地的贴身提点，
  绝不算流日吉凶（那会牵动易错的流日算法，违"准确性"底线）。
- 塔罗每日一张、按人+日期确定性（tarot.py）。

公共入口：
    daily_fortune(birth=None, d=None) -> dict
"""
from __future__ import annotations

from datetime import date as _date

from .almanac import today_almanac
from .tarot import daily_tarot

# 天干 → (五行, 是否阳)
_GAN = {
    "甲": ("木", True),  "乙": ("木", False),
    "丙": ("火", True),  "丁": ("火", False),
    "戊": ("土", True),  "己": ("土", False),
    "庚": ("金", True),  "辛": ("金", False),
    "壬": ("水", True),  "癸": ("水", False),
}
# 五行相生：木→火→土→金→水→木
_SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
# 五行相克：木→土→水→火→金→木
_KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

_ZHI_SHENGXIAO = {
    "子": "鼠", "丑": "牛", "寅": "虎", "卯": "兔", "辰": "龙", "巳": "蛇",
    "午": "马", "未": "羊", "申": "猴", "酉": "鸡", "戌": "狗", "亥": "猪",
}

# 十神 → 一句日内倾向（温和、留余地，不是断言）
_SHISHEN_TIP = {
    "比肩": "今日人际与协作的能量旺，主见也强；与人分工分利时多让一分，少些较劲。",
    "劫财": "今日行动力足、也容易冲动破财，大额开销和合伙的事缓一缓再定。",
    "食神": "今日宜表达、创作、好好吃顿饭，放松反而出灵感，别把自己绷太紧。",
    "伤官": "今日才思外露、点子多，留意言语锋芒——话到嘴边先过一遍脑子。",
    "正财": "今日宜务实、理账、按部就班，踏实把手头事做完，回报是稳的。",
    "偏财": "今日机会和人脉来得活，适合开拓社交；见好就收，别因贪多翻车。",
    "正官": "今日宜守规矩、处理正事与责任，按流程走会比平时顺。",
    "七杀": "今日外部压力或挑战偏明显，宜主动迎上别硬扛，把压力转成行动力。",
    "正印": "今日宜学习、休养、向长辈或贵人求助，慢一点反而快。",
    "偏印": "今日思虑偏多、适合独处钻研；留心别想太多，先动起来。",
}

_TONE_OPENER = {
    "good": "今天是个顺势的日子。",
    "neutral": "今天是平常的一天，平常心走就好。",
    "bad": "今天宜静不宜躁，稳住节奏别强求。",
}

# ── 今日分项运程（测测式四维，口径见文件头：基于日主×今日天干的能量倾向，非流日吉凶预测）──
_SHENG_INV = {"火": "木", "土": "火", "金": "土", "水": "金", "木": "水"}  # 谁生我
# 十神归类：扶身（印·比劫） vs 耗身（食伤·财·官杀）
_FU = {"比肩", "劫财", "正印", "偏印"}
_HAO = {"食神", "伤官", "正财", "偏财", "正官", "七杀"}
# 今日天干十神 → 主要被激活的人生领域
_SS_TO_ASPECT = {
    "比肩": "感情人际", "劫财": "财运",
    "食神": "事业学业", "伤官": "事业学业",
    "正财": "财运", "偏财": "财运",
    "正官": "事业学业", "七杀": "事业学业",
    "正印": "健康情绪", "偏印": "健康情绪",
}
_ASPECTS = ["事业学业", "财运", "感情人际", "健康情绪"]
# 黄历总评 level(1-5) → 分项基准星
_LEVEL_BASE = {1: 2, 2: 3, 3: 3, 4: 4, 5: 4}
# (领域, 倾向) → (一句解读, 一句行动建议)。倾向 good/flat/caution 三态
_ASPECT_LINES = {
    "事业学业": {
        "good":    ("脑子转得开、推进力强，适合处理要紧事、做关键决定。", "趁状态好，把拖着的硬骨头啃下来。"),
        "flat":    ("按部就班即可，没有大风浪也没有大突破。", "把手头事做扎实，不必强求亮眼。"),
        "caution": ("容易遇阻力或被打断，节奏会被打乱。", "别硬刚，留出缓冲，要紧事缓一缓再拍板。"),
    },
    "财运": {
        "good":    ("财气活络，进账或机会的信号偏正面。", "该谈的合作、该收的款，今天可以推进。"),
        "flat":    ("财务平稳，宜守不宜大动。", "按预算走，不为小利费神。"),
        "caution": ("破财或冲动消费的苗头，开销容易失控。", "大额支出和投资缓一天，先管住钱包。"),
    },
    "感情人际": {
        "good":    ("人缘顺、沟通顺，适合联络感情、修复关系。", "主动伸出橄榄枝，今天对方更容易接住。"),
        "flat":    ("关系平稳，各自安好。", "不必刻意经营，自然相处就好。"),
        "caution": ("沟通容易擦枪走火，情绪上头会伤人。", "话出口前先过一遍脑子，别在气头上下结论。"),
    },
    "健康情绪": {
        "good":    ("精神头足，身心轻快。", "适合运动、晒太阳，把好状态用起来。"),
        "flat":    ("身体无碍，情绪平稳。", "正常作息，别熬夜就好。"),
        "caution": ("容易累、容易烦，情绪和睡眠需留意。", "早点歇、给自己留白，别跟自己较劲。"),
    },
}
# 喜用五行 → 本命幸运色/吉位/幸运数（取命主喜用，属命主层稳定属性，非流日）
_WUXING_LUCKY = {
    "木": {"color": "青绿色", "direction": "东方", "numbers": "3、8"},
    "火": {"color": "红 · 橙色", "direction": "南方", "numbers": "2、7"},
    "土": {"color": "黄 · 棕色", "direction": "西南 · 中宫", "numbers": "5、0"},
    "金": {"color": "白 · 金色", "direction": "西方", "numbers": "4、9"},
    "水": {"color": "黑 · 蓝色", "direction": "北方", "numbers": "1、6"},
}


def _xiyong(shishen: str, ws_level: str) -> str:
    """据日主旺衰判断某十神是「喜」「忌」还是「平」（扶抑法）。"""
    if ws_level in ("极旺", "偏旺"):
        if shishen in _HAO:
            return "喜"
        if shishen in _FU:
            return "忌"
    elif ws_level in ("极弱", "偏弱"):
        if shishen in _FU:
            return "喜"
        if shishen in _HAO:
            return "忌"
    return "平"


def _yongshen_wuxing(dm_wx: str, ws_level: str) -> str:
    """命主喜用五行：身弱取「生我」(印)，身旺取「我生」(食伤泄秀)，中和取本气。"""
    if ws_level in ("偏弱", "极弱"):
        return _SHENG_INV.get(dm_wx, dm_wx)
    if ws_level in ("偏旺", "极旺"):
        return _SHENG.get(dm_wx, dm_wx)
    return dm_wx


def _build_aspects(today_ss: str, ws_level: str, overall_level: int, chong_hit: bool) -> list[dict]:
    """四维分项运程：哪个领域被今日十神激活、喜忌定吉凶倾向、冲日打折。"""
    activated = _SS_TO_ASPECT.get(today_ss, "")
    lean = _xiyong(today_ss, ws_level)
    base = _LEVEL_BASE.get(overall_level, 3)
    out: list[dict] = []
    for asp in _ASPECTS:
        focus = (asp == activated)
        if focus:
            tone = "good" if lean == "喜" else ("caution" if lean == "忌" else "flat")
            star = base + (1 if tone == "good" else (-1 if tone == "caution" else 0))
        else:
            tone = "flat"
            star = base
        if chong_hit and asp in ("感情人际", "健康情绪"):
            star -= 1
            if tone == "flat":
                tone = "caution"
        star = max(1, min(5, star))
        read, advice = _ASPECT_LINES[asp][tone]
        out.append({"domain": asp, "stars": star, "focus": focus, "text": read, "advice": advice})
    return out


def _shishen(day_master: str, target: str) -> str:
    """命主日主天干 day_master 看 target 天干，得十神名。"""
    dm = _GAN.get(day_master)
    tg = _GAN.get(target)
    if not dm or not tg:
        return ""
    (dm_wx, dm_yang), (tg_wx, tg_yang) = dm, tg
    same_pol = (dm_yang == tg_yang)
    if tg_wx == dm_wx:
        return "比肩" if same_pol else "劫财"
    if _SHENG.get(dm_wx) == tg_wx:          # 我生 → 食伤
        return "食神" if same_pol else "伤官"
    if _KE.get(dm_wx) == tg_wx:             # 我克 → 财
        return "偏财" if same_pol else "正财"
    if _KE.get(tg_wx) == dm_wx:             # 克我 → 官杀
        return "七杀" if same_pol else "正官"
    if _SHENG.get(tg_wx) == dm_wx:          # 生我 → 印
        return "偏印" if same_pol else "正印"
    return ""


def daily_fortune(birth: dict | None = None, d: _date | None = None) -> dict:
    """今日运势：黄历 + 塔罗 + 个人化提点。纯本地、确定性。"""
    d = d or _date.today()
    almanac = today_almanac(d)
    tarot = daily_tarot(birth, d)

    personal: dict = {"available": False, "tips": []}
    aspects: list[dict] = []
    lucky: dict = {}
    focus_domain = ""
    if birth and birth.get("date"):
        try:
            from . import paipan
            from .bazi_enrich import enrich_bazi
            chart = paipan(birth)
            bazi = chart["bazi"]
            day_master = bazi.get("day_master", "")
            day_master_wx = bazi.get("day_master_wuxing", "") or _GAN.get(day_master, ("", 0))[0]
            year_zhi = bazi["pillars"]["year"]["zhi"]
            shengxiao = _ZHI_SHENGXIAO.get(year_zhi, "")
            today_gan = almanac["ganzhi"]["day"][:1]
            ss = _shishen(day_master, today_gan)
            ws_level = (enrich_bazi(bazi).get("wangshuai") or {}).get("level", "")
            tips: list[str] = []
            if ss and ss in _SHISHEN_TIP:
                tips.append(_SHISHEN_TIP[ss])
            chong_hit = bool(shengxiao and almanac["chong"]["shengxiao"] == shengxiao)
            if chong_hit:
                tips.append(f"今日地支冲你的生肖（{shengxiao}）——老话说「冲则动」，"
                            f"宜静不宜动，重大决定不妨缓一天再拍板。")
            aspects = _build_aspects(ss, ws_level, almanac["overall"]["level"], chong_hit)
            focus_domain = _SS_TO_ASPECT.get(ss, "")
            yong = _yongshen_wuxing(day_master_wx, ws_level)
            lk = _WUXING_LUCKY.get(yong, {})
            if lk:
                lucky = {"wuxing": yong, **lk}
            personal = {
                "available": True,
                "day_master": day_master,
                "shengxiao": shengxiao,
                "today_shishen": ss,
                "wangshuai": ws_level,
                "chong_hit": chong_hit,
                "tips": tips,
            }
        except Exception as e:
            personal = {"available": False, "tips": [], "error": str(e)}

    return {
        "date": almanac["solar"],
        "greeting": _TONE_OPENER.get(almanac["overall"]["tone"], _TONE_OPENER["neutral"]),
        "almanac": almanac,
        "tarot": tarot,
        "personal": personal,
        "focus_domain": focus_domain,
        "aspects": aspects,
        "lucky": lucky,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(
        daily_fortune({"date": "2002-02-24", "time": "07:30", "gender": "male"}),
        ensure_ascii=False, indent=2))
