"""
Anima 命理排盘引擎（晞 专用）
====================================
确定性算法排盘，不依赖 LLM 猜测：
- bazi_engine: 基于 lunar-python 的八字四柱/藏干/十神/大运/纳音
- ziwei_engine: 基于 iztro-py（社区标准库 iztro 的纯 Python 移植）排盘，薄适配成 Anima 结构
  （命宫/身宫/十四主星/辅星煞星/生年四化/大限）；含年界 bug 运行时补丁

统一入口 paipan(birth) → 返回结构化命盘 dict，可直接灌给 worker 渲染 Markdown 命盘表。
"""
from .bazi_engine import bazi_paipan
from .ziwei_engine import ziwei_paipan
from .daily import daily_fortune
from .interpret import interpret_chart


def paipan(birth: dict) -> dict:
    """
    完整排盘：八字 + 紫微。

    birth 字段（来自 user.birth）：
      date   : 'YYYY-MM-DD'（公历，calendar=lunar 时为农历）
      time   : 'HH:MM'（可选，缺失则按 12:00 午时近似并标记 time_unknown）
      gender : 'male' | 'female'
      calendar : 'solar' | 'lunar'（默认 solar）
      place / lng / lat / tz : 出生地（暂用于显示，真太阳时校正留作 TODO）

    返回：{ "input": {...}, "bazi": {...}, "ziwei": {...} }
    """
    bazi = bazi_paipan(birth)
    ziwei = ziwei_paipan(birth)
    return {
        "input": _normalize_input(birth),
        "bazi": bazi,
        "ziwei": ziwei,
    }


def _normalize_input(birth: dict) -> dict:
    return {
        "date": birth.get("date", ""),
        "time": birth.get("time", ""),
        "gender": birth.get("gender", "male"),
        "calendar": birth.get("calendar", "solar"),
        "place": birth.get("place", ""),
        "time_unknown": not bool(birth.get("time")),
    }


__all__ = ["paipan", "bazi_paipan", "ziwei_paipan", "daily_fortune", "interpret_chart"]
