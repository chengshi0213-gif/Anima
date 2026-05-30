"""
八字排盘引擎 — 基于 lunar-python（确定性，无 LLM）
=================================================
渊海子平 / 子平真诠 体系：四柱、藏干、十神、纳音、大运、命宫身宫。

lunar-python 已验证：1995-08-15 06:30 → 四柱 乙亥 甲申 戊寅 乙卯，
日主戊，月令藏干 庚壬戊，大运（性别相关）准确。
"""
from __future__ import annotations
from datetime import datetime


def _parse_dt(birth: dict):
    """解析 date+time，返回 (year, month, day, hour, minute, time_unknown)。"""
    date_s = (birth.get("date") or "").strip()
    if not date_s:
        raise ValueError("缺少出生日期 birth.date")
    # 兼容 'YYYY-MM-DD' 与 'YYYY/MM/DD'
    date_s = date_s.replace("/", "-")
    y, m, d = [int(x) for x in date_s.split("-")[:3]]

    time_s = (birth.get("time") or "").strip()
    time_unknown = not time_s
    if time_unknown:
        hh, mm = 12, 0  # 未知时辰按午时近似，结果中标记
    else:
        time_s = time_s.replace("：", ":")
        parts = time_s.split(":")
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
    return y, m, d, hh, mm, time_unknown


def _to_solar(birth: dict):
    """根据 calendar 返回 lunar-python Solar 对象。"""
    from lunar_python import Solar, Lunar

    y, m, d, hh, mm, time_unknown = _parse_dt(birth)
    calendar = (birth.get("calendar") or "solar").lower()
    if calendar == "lunar":
        # 农历转公历（闰月暂按非闰处理；前端采集以公历为主）
        lunar = Lunar.fromYmdHms(y, m, d, hh, mm, 0)
        solar = lunar.getSolar()
    else:
        solar = Solar.fromYmdHms(y, m, d, hh, mm, 0)
    return solar, time_unknown


def _pillar(gan_zhi: str, hide_gan, shishen_gan: str,
            shishen_zhi, nayin: str) -> dict:
    """组装单柱结构。"""
    return {
        "ganzhi": gan_zhi,
        "gan": gan_zhi[0] if gan_zhi else "",
        "zhi": gan_zhi[1] if len(gan_zhi) > 1 else "",
        "hide_gan": list(hide_gan),
        "shishen_gan": shishen_gan,   # 天干十神（日柱为「日主」）
        "shishen_zhi": list(shishen_zhi),  # 地支藏干对应十神
        "nayin": nayin,
    }


def bazi_paipan(birth: dict) -> dict:
    """
    返回结构化八字命盘 dict：
      {
        "solar": "1995-08-15 06:30", "lunar": "一九九五年七月二十",
        "day_master": "戊", "day_master_wuxing": "土",
        "pillars": {"year":{...}, "month":{...}, "day":{...}, "time":{...}},
        "ming_gong": "壬午", "shen_gong": "戊子",
        "qiyun": {...}, "dayun": [{...}],
        "time_unknown": bool,
      }
    """
    solar, time_unknown = _to_solar(birth)
    lunar = solar.getLunar()
    ec = lunar.getEightChar()

    gender = (birth.get("gender") or "male").lower()
    gender_code = 1 if gender == "male" else 0

    day_gan = ec.getDayGan()
    pillars = {
        "year": _pillar(ec.getYear(), ec.getYearHideGan(),
                        ec.getYearShiShenGan(), ec.getYearShiShenZhi(),
                        ec.getYearNaYin()),
        "month": _pillar(ec.getMonth(), ec.getMonthHideGan(),
                         ec.getMonthShiShenGan(), ec.getMonthShiShenZhi(),
                         ec.getMonthNaYin()),
        "day": _pillar(ec.getDay(), ec.getDayHideGan(),
                       "日主", ec.getDayShiShenZhi(),
                       ec.getDayNaYin()),
        "time": _pillar(ec.getTime(), ec.getTimeHideGan(),
                        ec.getTimeShiShenGan(), ec.getTimeShiShenZhi(),
                        ec.getTimeNaYin()),
    }

    # 大运（性别 + 年干阴阳决定顺逆，lunar-python 内部已处理）
    dayun_list = []
    try:
        yun = ec.getYun(gender_code)
        qiyun = {
            "start_year": yun.getStartYear(),
            "start_month": yun.getStartMonth(),
            "start_day": yun.getStartDay(),
            "start_solar": yun.getStartSolar().toYmd() if hasattr(yun, "getStartSolar") else "",
        }
        for d in yun.getDaYun():
            gz = d.getGanZhi()
            if not gz:
                continue  # index 0 起运前空柱
            dayun_list.append({
                "start_age": d.getStartAge(),
                "start_year": d.getStartYear(),
                "ganzhi": gz,
            })
    except Exception as e:
        qiyun = {"error": f"大运计算异常: {e}"}

    return {
        "solar": solar.toYmdHms() if not time_unknown else solar.toYmd() + " (时辰未知)",
        "lunar": f"{lunar.getYearInChinese()}年{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
        "lunar_month": lunar.getMonth(),   # 含闰月负数标记
        "lunar_day": lunar.getDay(),
        "day_master": day_gan,
        "day_master_wuxing": _GAN_WUXING.get(day_gan, ""),
        "pillars": pillars,
        "ming_gong": ec.getMingGong(),
        "shen_gong": ec.getShenGong(),
        "qiyun": qiyun,
        "dayun": dayun_list,
        "time_unknown": time_unknown,
    }


_GAN_WUXING = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}


if __name__ == "__main__":
    import json
    chart = bazi_paipan({"date": "1995-08-15", "time": "06:30", "gender": "male"})
    print(json.dumps(chart, ensure_ascii=False, indent=2))
