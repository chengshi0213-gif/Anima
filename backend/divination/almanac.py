#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
almanac.py — 今日黄历（老黄历 / 通胜）

数据源 = lunar-python（八字引擎已依赖，无需新增依赖）。lunar-python 实现的是
港台通行的权威黄历算法：宜/忌、吉神/凶煞、冲煞生肖与方位、彭祖百忌、二十八宿、
建除十二值神、黄道黑道吉凶、当日节气。本模块只做"结构化抽取 + 今日吉凶总评"，
不做任何主观演绎，保证准确性。个人化（结合命主八字/生肖）在 daily.py 里做。

公共入口：
    today_almanac(d=None) -> dict   # d 为 datetime.date，缺省=系统今天
"""
from __future__ import annotations

from datetime import date as _date


def _safe(fn, default=None):
    """lunar-python 各版本个别 getter 名称会变，逐个兜底，缺失不致整体崩。"""
    try:
        v = fn()
        return v if v is not None else default
    except Exception:
        return default


# 建除十二值神的通行吉凶倾向（黄历"黄黑道"之外的一层参考）
_ZHIXING_LUCK = {
    "建": "小吉", "除": "吉", "满": "凶", "平": "平",
    "定": "吉", "执": "小吉", "破": "大凶", "危": "凶",
    "成": "大吉", "收": "凶", "开": "吉", "闭": "凶",
}

# 今日吉凶总评：以 lunar 计算的"黄道/黑道"为主轴（最权威），值神倾向为辅
def _overall(tianshen_luck: str | None, zhixing: str | None) -> dict:
    """返回 {level: 1..5, label, tone}。5=大吉 1=诸事不宜。"""
    zx = _ZHIXING_LUCK.get(zhixing or "", "")
    huangdao = (tianshen_luck == "吉")  # 黄道吉日
    if huangdao and zx in ("大吉", "吉"):
        return {"level": 5, "label": "大吉", "tone": "good"}
    if huangdao:
        return {"level": 4, "label": "吉", "tone": "good"}
    if zx == "大吉":
        return {"level": 4, "label": "吉", "tone": "good"}
    if zx in ("吉", "小吉"):
        return {"level": 3, "label": "平", "tone": "neutral"}
    if tianshen_luck == "凶" and zx in ("大凶", "凶"):
        return {"level": 1, "label": "诸事宜静", "tone": "bad"}
    if tianshen_luck == "凶":
        return {"level": 2, "label": "小凶", "tone": "bad"}
    return {"level": 3, "label": "平", "tone": "neutral"}


def today_almanac(d: _date | None = None) -> dict:
    """结构化今日黄历。纯本地计算，绝不联网。"""
    from lunar_python import Solar

    d = d or _date.today()
    solar = Solar.fromYmd(d.year, d.month, d.day)
    lunar = solar.getLunar()

    tianshen_luck = _safe(lunar.getDayTianShenLuck)        # '吉' / '凶'（黄道/黑道）
    zhixing = _safe(lunar.getZhiXing)                      # 建除十二值神，如 '执'
    overall = _overall(tianshen_luck, zhixing)

    # 二十八宿："井木犴" = 宿 + 七政 + 禽
    xiu = _safe(lunar.getXiu, "")
    xiu_full = f"{xiu}{_safe(lunar.getZheng, '')}{_safe(lunar.getAnimal, '')}".strip()

    return {
        "solar": f"{d.year:04d}-{d.month:02d}-{d.day:02d}",
        "weekday": "星期" + "日一二三四五六"[(d.weekday() + 1) % 7],
        "lunar_date": f"{_safe(lunar.getYearInChinese, '')}年"
                      f"{_safe(lunar.getMonthInChinese, '')}月"
                      f"{_safe(lunar.getDayInChinese, '')}",
        "ganzhi": {
            "year":  _safe(lunar.getYearInGanZhi, ""),
            "month": _safe(lunar.getMonthInGanZhi, ""),
            "day":   _safe(lunar.getDayInGanZhi, ""),
        },
        "day_shengxiao": _safe(lunar.getDayShengXiao, ""),  # 当日生肖（日支）
        "overall": overall,                                  # 今日吉凶总评
        "yi": list(_safe(lunar.getDayYi, []) or []),         # 宜
        "ji": list(_safe(lunar.getDayJi, []) or []),         # 忌
        "ji_shen": list(_safe(lunar.getDayJiShen, []) or []),    # 吉神宜趋
        "xiong_sha": list(_safe(lunar.getDayXiongSha, []) or []),# 凶煞宜忌
        "chong": {
            "shengxiao": _safe(lunar.getDayChongShengXiao, ""),  # 所冲生肖，如 '蛇'
            "desc": _safe(lunar.getDayChongDesc, ""),            # '(丁巳)蛇'
            "sha": _safe(lunar.getDaySha, ""),                   # 煞方，如 '西'
        },
        "peng_zu": [s for s in (_safe(lunar.getPengZuGan, ""),
                                _safe(lunar.getPengZuZhi, "")) if s],  # 彭祖百忌
        "zhixing": zhixing,                                   # 建除值神
        "tian_shen": {
            "name": _safe(lunar.getDayTianShen, ""),          # 当值天神，如 '朱雀'
            "type": _safe(lunar.getDayTianShenType, ""),      # '黄道' / '黑道'
            "luck": tianshen_luck,                            # '吉' / '凶'
        },
        "xiu": xiu_full,                                      # 二十八宿
        "jieqi": {
            "prev": _jieqi_name(lunar, "getPrevJieQi"),
            "next": _jieqi_name(lunar, "getNextJieQi"),
        },
    }


def _jieqi_name(lunar, getter: str) -> str:
    try:
        jq = getattr(lunar, getter)()
        return jq.getName() if jq else ""
    except Exception:
        return ""


if __name__ == "__main__":
    import json
    print(json.dumps(today_almanac(), ensure_ascii=False, indent=2))
