"""
紫微斗数排盘引擎 — 自研纯 Python（确定性，无外部依赖，可 PyInstaller 打包）
=============================================================================
依赖 lunar-python 仅取「农历月/日 + 年干支 + 时支」，其余全为查表+算法。
体系：紫微斗数全书 / 中州派。

算法来源：references/ziwei-paipan.md（命宫身宫定位、五行局、紫微星位推算、
十四主星、辅星煞星、生年四化、大限）。

地支索引约定：子=0 丑=1 寅=2 卯=3 辰=4 巳=5 午=6 未=7 申=8 酉=9 戌=10 亥=11
天干索引约定：甲=0 乙=1 丙=2 丁=3 戊=4 己=5 庚=6 辛=7 壬=8 癸=9
"""
from __future__ import annotations

ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]

# 十二宫名（从命宫起，逆时针 = 地支索引递减方向）
PALACE_NAMES = ["命宫", "兄弟", "夫妻", "子女", "财帛", "疾厄",
                "迁移", "交友", "官禄", "田宅", "福德", "父母"]

# 五虎遁：年干 → 寅宫起始天干索引
WUHU_DUN = {0: 2, 5: 2,   # 甲己 → 丙
            1: 4, 6: 4,   # 乙庚 → 戊
            2: 6, 7: 6,   # 丙辛 → 庚
            3: 8, 8: 8,   # 丁壬 → 壬
            4: 0, 9: 0}   # 戊癸 → 甲

# 60甲子纳音 → 五行局数（水2/木3/金4/土5/火6）
# 纳音五行表（按 60 甲子顺序，每两柱同一纳音）
NAYIN_WUXING = [
    "金", "金", "火", "火", "木", "木", "土", "土", "金", "金",  # 甲子..癸酉
    "火", "火", "水", "水", "土", "土", "金", "金", "木", "木",  # 甲戌..癸未
    "水", "水", "土", "土", "火", "火", "木", "木", "土", "土",  # 甲申..癸巳
    "金", "金", "木", "木", "水", "水", "土", "土", "火", "火",  # 甲午..癸卯
    "木", "木", "土", "土", "金", "金", "火", "火", "水", "水",  # 甲辰..癸丑
    "土", "土", "火", "火", "木", "木", "水", "水", "金", "金",  # 甲寅..癸亥
]
WUXING_JU = {"水": 2, "木": 3, "金": 4, "土": 5, "火": 6}
JU_NAME = {2: "水二局", 3: "木三局", 4: "金四局", 5: "土五局", 6: "火六局"}

# 紫微星系（逆时针，相对紫微的偏移，负=逆）
ZIWEI_SERIES = [("紫微", 0), ("天机", -1), ("太阳", -3),
                ("武曲", -4), ("天同", -5), ("廉贞", -8)]
# 天府星系（顺时针，相对天府的偏移）
TIANFU_SERIES = [("天府", 0), ("太阴", 1), ("贪狼", 2), ("巨门", 3),
                 ("天相", 4), ("天梁", 5), ("七杀", 6), ("破军", 10)]

# 生年四化表：年干索引 → {化禄,化权,化科,化忌}
SIHUA = {
    0: ("廉贞", "破军", "武曲", "太阳"),  # 甲
    1: ("天机", "天梁", "紫微", "太阴"),  # 乙
    2: ("天同", "天机", "文昌", "廉贞"),  # 丙
    3: ("太阴", "天同", "天机", "巨门"),  # 丁
    4: ("贪狼", "太阴", "右弼", "天机"),  # 戊
    5: ("武曲", "贪狼", "天梁", "文曲"),  # 己
    6: ("太阳", "武曲", "太阴", "天同"),  # 庚
    7: ("巨门", "太阳", "文曲", "文昌"),  # 辛
    8: ("天梁", "紫微", "左辅", "武曲"),  # 壬
    9: ("破军", "巨门", "太阴", "贪狼"),  # 癸
}
SIHUA_LABELS = ["化禄", "化权", "化科", "化忌"]

# 天魁/天钺/禄存 按年干（索引甲..癸），值为地支索引
TIANKUI = [1, 0, 11, 9, 8, 7, 6, 6, 5, 3]   # 丑子亥酉申未午午巳卯
TIANYUE = [7, 8, 9, 11, 0, 1, 2, 2, 3, 5]   # 未申酉亥子丑寅寅卯巳
LUCUN  = [2, 3, 5, 6, 5, 6, 8, 9, 11, 0]    # 寅卯巳午巳午申酉亥子

# 天马：按年支三合 → 地支索引
def _tianma(year_zhi: int) -> int:
    group = year_zhi % 4  # 申子辰=0组? 用三合判断
    # 寅午戌→申, 申子辰→寅, 巳酉丑→亥, 亥卯未→巳
    if year_zhi in (2, 6, 10):   # 寅午戌
        return 8
    if year_zhi in (8, 0, 4):    # 申子辰
        return 2
    if year_zhi in (5, 9, 1):    # 巳酉丑
        return 11
    return 5                      # 亥卯未

# 火星/铃星起宫（按年支三合），再从起宫起子时顺数至生时
def _huoxing_start(year_zhi: int) -> int:
    if year_zhi in (2, 6, 10):   # 寅午戌 → 丑
        return 1
    if year_zhi in (8, 0, 4):    # 申子辰 → 寅
        return 2
    if year_zhi in (5, 9, 1):    # 巳酉丑 → 卯
        return 3
    return 9                      # 亥卯未 → 酉

def _lingxing_start(year_zhi: int) -> int:
    if year_zhi in (2, 6, 10):   # 寅午戌 → 卯
        return 3
    return 10                     # 其余 → 戌


def _ziwei_position(day: int, ju: int) -> int:
    """紫微星所在地支索引。day=农历日, ju=五行局数。"""
    x = 0
    while (day + x) % ju != 0:
        x += 1
    c = (day + x) // ju
    if x % 2 == 0:
        d = c + x
    else:
        d = c - x
        while d < 0:
            d += 12
    # D 对应宫位：寅1·卯2...，归一到 1..12
    d = ((d - 1) % 12) + 1
    # 寅=index2 起，position p → branch index (1 + p) % 12
    return (1 + d) % 12


def _palace_gan(branch: int, year_gan: int) -> str:
    """五虎遁求某地支宫位的天干。"""
    yin_gan = WUHU_DUN[year_gan]           # 寅宫天干索引
    gan_idx = (yin_gan + (branch - 2)) % 10
    return GAN[gan_idx]


def _parse_for_ziwei(birth: dict):
    """取农历月/日、年干支索引、时支索引、性别。复用 bazi_engine 的解析。"""
    from .bazi_engine import _to_solar
    solar, time_unknown = _to_solar(birth)
    lunar = solar.getLunar()
    ec = lunar.getEightChar()

    lunar_month = abs(lunar.getMonth())     # 闰月取绝对值
    lunar_day = lunar.getDay()
    year_gan = GAN.index(ec.getYearGan())
    year_zhi = ZHI.index(ec.getYearZhi())
    time_zhi = ZHI.index(ec.getTimeZhi())
    gender = (birth.get("gender") or "male").lower()
    return {
        "lunar_month": lunar_month, "lunar_day": lunar_day,
        "year_gan": year_gan, "year_zhi": year_zhi,
        "time_zhi": time_zhi, "gender": gender,
        "time_unknown": time_unknown,
        "year_ganzhi": ec.getYear(),
    }


def ziwei_paipan(birth: dict) -> dict:
    """返回结构化紫微命盘。"""
    d = _parse_for_ziwei(birth)
    m = d["lunar_month"]
    h = d["time_zhi"]
    year_gan = d["year_gan"]
    year_zhi = d["year_zhi"]

    # ── 命宫 / 身宫 ──
    # 寅(2)起正月顺数至生月 → 月宫；命宫=月宫逆数生时；身宫=月宫顺数生时
    month_palace = (2 + (m - 1)) % 12
    ming = (month_palace - h) % 12
    shen = (month_palace + h) % 12

    # ── 五行局（命宫干支纳音）──
    ming_gan = _palace_gan(ming, year_gan)
    ming_gan_idx = GAN.index(ming_gan)
    # 60甲子序号 = 由干支反推
    jiazi_idx = _ganzhi_to_index(ming_gan_idx, ming)
    wuxing = NAYIN_WUXING[jiazi_idx]
    ju = WUXING_JU[wuxing]

    # ── 紫微 & 天府 ──
    ziwei_pos = _ziwei_position(d["lunar_day"], ju)
    tianfu_pos = (4 - ziwei_pos) % 12

    # ── 十四主星落宫 ──
    star_at = {i: [] for i in range(12)}   # branch index → [星名]
    for name, off in ZIWEI_SERIES:
        star_at[(ziwei_pos + off) % 12].append(name)
    for name, off in TIANFU_SERIES:
        star_at[(tianfu_pos + off) % 12].append(name)

    # ── 辅星煞星 ──
    aux = {
        "左辅": (4 + (m - 1)) % 12,
        "右弼": (10 - (m - 1)) % 12,
        "文昌": (10 - h) % 12,
        "文曲": (4 + h) % 12,
        "天魁": TIANKUI[year_gan],
        "天钺": TIANYUE[year_gan],
        "禄存": LUCUN[year_gan],
        "擎羊": (LUCUN[year_gan] + 1) % 12,
        "陀罗": (LUCUN[year_gan] - 1) % 12,
        "火星": (_huoxing_start(year_zhi) + h) % 12,
        "铃星": (_lingxing_start(year_zhi) + h) % 12,
        "天马": _tianma(year_zhi),
        "地空": (11 - h) % 12,
        "地劫": (11 + h) % 12,
    }
    for name, pos in aux.items():
        star_at[pos].append(name)

    # ── 生年四化 ──
    lu, quan, ke, ji = SIHUA[year_gan]
    sihua = {"化禄": lu, "化权": quan, "化科": ke, "化忌": ji}

    # ── 大限 ──
    year_yang = (year_gan % 2 == 0)         # 甲丙戊庚壬=阳
    male = (d["gender"] == "male")
    # 阳男阴女顺，阴男阳女逆
    forward = (year_yang and male) or ((not year_yang) and (not male))
    daxian = []
    for k in range(12):
        branch = (ming + k) % 12 if forward else (ming - k) % 12
        start_age = ju + 10 * k
        daxian.append({
            "branch": ZHI[branch],
            "branch_index": branch,
            "age_range": [start_age, start_age + 9],
        })

    # ── 组装十二宫（从命宫逆时针 = 索引递减）──
    palaces = []
    for i, pname in enumerate(PALACE_NAMES):
        branch = (ming - i) % 12
        gan = _palace_gan(branch, year_gan)
        stars = star_at[branch]
        # 标注四化
        star_objs = []
        for s in stars:
            tags = [lbl for lbl, star in zip(SIHUA_LABELS, (lu, quan, ke, ji)) if star == s]
            star_objs.append({"name": s, "sihua": tags})
        palaces.append({
            "name": pname,
            "ganzhi": gan + ZHI[branch],
            "branch": ZHI[branch],
            "branch_index": branch,
            "is_shen_gong": branch == shen,
            "stars": star_objs,
        })

    return {
        "ming_gong": {"branch": ZHI[ming], "ganzhi": ming_gan + ZHI[ming]},
        "shen_gong": {"branch": ZHI[shen]},
        "wuxing_ju": JU_NAME[ju],
        "ju_number": ju,
        "ziwei_branch": ZHI[ziwei_pos],
        "tianfu_branch": ZHI[tianfu_pos],
        "sihua": sihua,
        "palaces": palaces,
        "daxian": daxian,
        "time_unknown": d["time_unknown"],
        "year_ganzhi": d["year_ganzhi"],
    }


def _ganzhi_to_index(gan_idx: int, zhi_idx: int) -> int:
    """由天干索引+地支索引求 60 甲子序号（0..59）。"""
    for i in range(60):
        if i % 10 == gan_idx and i % 12 == zhi_idx:
            return i
    raise ValueError(f"非法干支组合 gan={gan_idx} zhi={zhi_idx}")


if __name__ == "__main__":
    import json
    chart = ziwei_paipan({"date": "1995-08-15", "time": "06:30", "gender": "male"})
    print(json.dumps(chart, ensure_ascii=False, indent=2))
