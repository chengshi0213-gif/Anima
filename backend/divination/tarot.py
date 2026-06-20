#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tarot.py — 今日塔罗（每日一张·按人+日期确定性·含正逆位）

设计（用户拍板）：同一个人当天恒定抽到同一张牌、同一正逆位，跨次调用不变，次日才换。
做法：用 (命主标识 + 当日公历日期) 做 SHA-256 种子，确定性地选牌与正/逆位。
不联网、不随机、可复现——既有"今日专属"的仪式感，又便于测试与缓存。

牌库见 tarot_deck.TAROT_DECK（莱德-韦特 78 张，离线纯数据）。

公共入口：
    daily_tarot(birth=None, d=None) -> dict
"""
from __future__ import annotations

import hashlib
from datetime import date as _date


def _person_key(birth: dict | None) -> str:
    """命主稳定标识：用出生信息派生，无出生信息则归为 guest。
    同一命主标识恒定 → 抽牌按人区分但不泄露身份。"""
    if not birth:
        return "guest"
    parts = [str(birth.get("date", "")), str(birth.get("time", "")),
             str(birth.get("gender", "")), str(birth.get("calendar", ""))]
    return "|".join(parts) or "guest"


def _seed_int(person_key: str, iso_date: str) -> int:
    h = hashlib.sha256(f"{person_key}@{iso_date}".encode("utf-8")).hexdigest()
    return int(h, 16)


def daily_tarot(birth: dict | None = None, d: _date | None = None) -> dict:
    """返回今日塔罗牌（确定性）。"""
    from .tarot_deck import TAROT_DECK

    d = d or _date.today()
    iso = f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
    seed = _seed_int(_person_key(birth), iso)

    card = TAROT_DECK[seed % len(TAROT_DECK)]
    reversed_ = bool((seed // len(TAROT_DECK)) % 2)
    orient = "reversed" if reversed_ else "upright"

    return {
        "date": iso,
        "id": card["id"],
        "name_zh": card["name_zh"],
        "name_en": card["name_en"],
        "arcana": card["arcana"],
        "suit": card.get("suit"),
        "rank": card.get("rank"),
        "orientation": orient,            # upright / reversed
        "orientation_zh": "逆位" if reversed_ else "正位",
        "keywords": card["reversed_keywords"] if reversed_ else card["upright_keywords"],
        "meaning": card["reversed"] if reversed_ else card["upright"],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(daily_tarot({"date": "2002-02-24", "time": "07:30", "gender": "male"}),
                     ensure_ascii=False, indent=2))
