"""
紫微斗数排盘 — 适配 iztro-py（纯 Python 真 iztro 移植）
=============================================================================
弃用自研引擎：自研版曾多处线上 bug（纳音表错乱致 47% 五行局错 / 子丑宫干 /
立春 vs 正月初一年界），单命例测试长期"假绿"放过。改"该抄就抄"——直接对接社区
标准库 iztro 的纯 Python 移植 iztro-py（pip: iztro-py，依赖全纯 Python，可 PyInstaller 打包，
复用 Anima 已有的 lunar_python），再薄薄映射成 Anima 既有 ziwei dict 结构（下游 render/测试零改动）。

八字仍由 bazi_engine（lunar-python）负责，本模块只管紫微。
正确性对账：tests/test_ziwei_crossval.py（差分真 iztro-JS 2.5.x golden）+ 属性测试。
详见 memory anima-divination-audit。

iztro-py 的地支/天干/宫名字段返回 i18n key（如 'xuEarthly'/'gengHeavenly'/'soulPalace'），
均为稳定枚举，此处硬编码中译；星名用 star.translate_name()。
"""
from __future__ import annotations

# i18n key → 中文
_BRANCH = {"ziEarthly": "子", "chouEarthly": "丑", "yinEarthly": "寅", "maoEarthly": "卯",
           "chenEarthly": "辰", "siEarthly": "巳", "wuEarthly": "午", "weiEarthly": "未",
           "shenEarthly": "申", "youEarthly": "酉", "xuEarthly": "戌", "haiEarthly": "亥"}
_BRANCH_IDX = {z: i for i, z in enumerate(
    ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"])}
_STEM = {"jiaHeavenly": "甲", "yiHeavenly": "乙", "bingHeavenly": "丙", "dingHeavenly": "丁",
         "wuHeavenly": "戊", "jiHeavenly": "己", "gengHeavenly": "庚", "xinHeavenly": "辛",
         "renHeavenly": "壬", "guiHeavenly": "癸"}
_PALACE = {"soulPalace": "命宫", "siblingsPalace": "兄弟", "spousePalace": "夫妻",
           "childrenPalace": "子女", "wealthPalace": "财帛", "healthPalace": "疾厄",
           "surfacePalace": "迁移", "friendsPalace": "交友", "careerPalace": "官禄",
           "propertyPalace": "田宅", "spiritPalace": "福德", "parentsPalace": "父母"}
_JU_NUM = {"水二局": 2, "木三局": 3, "金四局": 4, "土五局": 5, "火六局": 6}
_MUTAGEN = {"禄": "化禄", "权": "化权", "科": "化科", "忌": "化忌"}
_GENDER = {"male": "男", "female": "女"}

# Anima 十二宫规范顺序（命宫起，逆时针）
_PALACE_ORDER = ["命宫", "兄弟", "夫妻", "子女", "财帛", "疾厄",
                 "迁移", "交友", "官禄", "田宅", "福德", "父母"]


def _time_index(hour: int) -> int:
    """公历小时 → iztro 时辰索引（0..12，0=早子时 12=晚子时）。"""
    return min(12, (hour + 1) // 2)


_IZTRO_PATCHED = False


def _ensure_iztro_patched() -> None:
    """修正 iztro-py 端口的年界 bug。

    iztro-py（pin: iztro-py==0.3.4 见 requirements）在 utils/calendar.py 用
    `getYearInGanZhiExact()`（**立春**分界，八字约定）推全盘年干支，但紫微斗数应按
    **农历正月初一**分界（`getYearInGanZhi()`）。后果：立春~农历新年窗口（每年约两周）
    出生者，五虎遁宫干 / 五行局 / 生年四化 / 大限阴阳 全错（命宫干甚至差一柱）。
    真 iztro-JS 用的是正月初一，此补丁把 iztro-py 对齐到 iztro-JS。

    做法：包装原函数，只把 year_stem/year_branch 改回正月初一（model_copy 不破坏其余字段），
    再替换所有已 import 该函数的 iztro_py 子模块绑定（astro/palace/horoscope 各有独立绑定）。
    回归兜底：tests/test_ziwei_crossval.py 含 1996-02-12 等边界例，补丁失效会立刻变红。
    """
    global _IZTRO_PATCHED
    if _IZTRO_PATCHED:
        return
    import sys
    from iztro_py import by_solar as _force_load  # noqa: F401  触发所有子模块加载
    from iztro_py.utils import calendar as _cal
    from lunar_python import Solar as _Solar

    _orig = _cal.get_heavenly_stem_and_earthly_branch_date

    def _patched(year, month, day, time_index, *args, **kwargs):
        res = _orig(year, month, day, time_index, *args, **kwargs)
        lunar = _Solar.fromYmdHms(year, month, day, 12, 0, 0).getLunar()
        ys, yb = _cal._parse_ganzhi(lunar.getYearInGanZhi())  # 正月初一
        return res.model_copy(update={"year_stem": ys, "year_branch": yb})

    for _name, _mod in list(sys.modules.items()):
        if _name.startswith("iztro_py") and \
                getattr(_mod, "get_heavenly_stem_and_earthly_branch_date", None) is _orig:
            _mod.get_heavenly_stem_and_earthly_branch_date = _patched
    _IZTRO_PATCHED = True


def ziwei_paipan(birth: dict) -> dict:
    """返回结构化紫微命盘（iztro-py 排盘 → Anima dict）。"""
    _ensure_iztro_patched()
    from iztro_py import by_solar
    from .bazi_engine import _to_solar

    solar, time_unknown = _to_solar(birth)
    y, mo, d, hh = solar.getYear(), solar.getMonth(), solar.getDay(), solar.getHour()
    gender = _GENDER.get((birth.get("gender") or "male").lower(), "男")
    # 生年干支按正月初一分界（与紫微斗数 / iztro 一致，非八字立春）
    year_ganzhi = solar.getLunar().getYearInGanZhi()

    a = by_solar(f"{y}-{mo}-{d}", _time_index(hh), gender)
    body_branch = _BRANCH[a.earthly_branch_of_body_palace]

    # 生年四化：扫描所有宫的主星+辅星 mutagen（本命盘 scope=origin）
    sihua = {"化禄": "", "化权": "", "化科": "", "化忌": ""}
    for p in a.palaces:
        for s in list(p.major_stars) + list(p.minor_stars):
            if s.mutagen:
                sihua[_MUTAGEN[s.mutagen]] = s.translate_name()

    by_name: dict[str, dict] = {}
    ziwei_branch = tianfu_branch = ""
    for p in a.palaces:
        branch = _BRANCH[p.earthly_branch]
        name = _PALACE[p.name]
        stars = []
        for s in list(p.major_stars) + list(p.minor_stars):  # 主星+辅煞，不含杂曜
            nm = s.translate_name()
            stars.append({"name": nm, "sihua": [_MUTAGEN[s.mutagen]] if s.mutagen else []})
            if nm == "紫微":
                ziwei_branch = branch
            elif nm == "天府":
                tianfu_branch = branch
        by_name[name] = {
            "name": name,
            "ganzhi": _STEM[p.heavenly_stem] + branch,
            "branch": branch,
            "branch_index": _BRANCH_IDX[branch],
            "is_shen_gong": branch == body_branch,
            "stars": stars,
            "_range": tuple(p.decadal.range),
        }

    # 十二宫按规范顺序输出（剥离内部 _range）
    palaces = []
    for nm in _PALACE_ORDER:
        pp = {k: v for k, v in by_name[nm].items() if k != "_range"}
        palaces.append(pp)

    # 大限：各宫 decadal.range，按起运岁升序（即顺/逆行方向）
    daxian = sorted(
        ({"branch": p["branch"], "branch_index": p["branch_index"],
          "age_range": [p["_range"][0], p["_range"][1]]}
         for p in by_name.values()),
        key=lambda x: x["age_range"][0],
    )

    ming = by_name["命宫"]
    return {
        "ming_gong": {"branch": ming["branch"], "ganzhi": ming["ganzhi"]},
        "shen_gong": {"branch": body_branch},
        "wuxing_ju": a.five_elements_class,
        "ju_number": _JU_NUM.get(a.five_elements_class, 0),
        "ziwei_branch": ziwei_branch,
        "tianfu_branch": tianfu_branch,
        "sihua": sihua,
        "palaces": palaces,
        "daxian": daxian,
        "time_unknown": time_unknown,
        "year_ganzhi": year_ganzhi,
    }


if __name__ == "__main__":
    import json
    chart = ziwei_paipan({"date": "1995-08-15", "time": "06:30", "gender": "male"})
    print(json.dumps(chart, ensure_ascii=False, indent=2))
