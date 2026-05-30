"""
命盘 Markdown 渲染 — 把 paipan() 的结构化输出转成可读命盘表。
晞 worker 可直接把这段 Markdown 嵌进回复（八字四柱表 + 紫微十二宫盘）。
"""
from __future__ import annotations

# 紫微十二宫按标准盘面 4×4 外圈布局（地支固定位置）
# 盘面：
#   巳  午  未  申
#   辰          酉
#   卯          戌
#   寅  丑  子  亥
_GRID_LAYOUT = [
    ["巳", "午", "未", "申"],
    ["辰", None, None, "酉"],
    ["卯", None, None, "戌"],
    ["寅", "丑", "子", "亥"],
]


def render_bazi_md(bazi: dict) -> str:
    p = bazi["pillars"]
    cols = ["year", "month", "day", "time"]
    head = ["", "年柱", "月柱", "日柱", "时柱"]
    rows = [
        ["天干"] + [p[c]["gan"] for c in cols],
        ["地支"] + [p[c]["zhi"] for c in cols],
        ["藏干"] + ["、".join(p[c]["hide_gan"]) for c in cols],
        ["十神"] + [p[c]["shishen_gan"] for c in cols],
        ["纳音"] + [p[c]["nayin"] for c in cols],
    ]
    lines = ["| " + " | ".join(head) + " |",
             "|" + "---|" * len(head)]
    for r in rows:
        lines.append("| " + " | ".join(r) + " |")
    table = "\n".join(lines)

    dy = "、".join(f"{d['start_age']}岁 {d['ganzhi']}" for d in bazi["dayun"][:8])
    note = "（时辰未知，时柱按午时近似）\n" if bazi.get("time_unknown") else ""

    return (
        f"**八字命盘**　{bazi['solar']}　{bazi['lunar']}\n{note}"
        f"日主：{bazi['day_master']}（{bazi['day_master_wuxing']}）　"
        f"命宫：{bazi['ming_gong']}　身宫：{bazi['shen_gong']}\n\n"
        f"{table}\n\n"
        f"**大运：** {dy}"
    )


def render_ziwei_md(ziwei: dict) -> str:
    # 地支 → 宫位信息
    by_branch = {p["branch"]: p for p in ziwei["palaces"]}

    def cell(branch: str) -> str:
        p = by_branch.get(branch)
        if not p:
            return ""
        flag = "·身" if p["is_shen_gong"] else ""
        stars = "<br>".join(
            s["name"] + ("".join(f"({t})" for t in s["sihua"]) if s["sihua"] else "")
            for s in p["stars"]
        ) or "—"
        return f"**{p['name']}{flag}** {p['ganzhi']}<br>{stars}"

    lines = []
    for row in _GRID_LAYOUT:
        cells = []
        if row[1] is None and row[2] is None:
            # 中宫行：只渲染左右
            cells = [cell(row[0]), "", "", cell(row[3])]
        else:
            cells = [cell(b) if b else "" for b in row]
        lines.append("| " + " | ".join(cells) + " |")

    grid = "|   |   |   |   |\n|---|---|---|---|\n" + "\n".join(lines)

    sh = ziwei["sihua"]
    sihua_line = "　".join(f"{k}{v}" for k, v in sh.items())
    note = "（时辰未知，命盘仅供参考）\n" if ziwei.get("time_unknown") else ""

    return (
        f"**紫微命盘**　{ziwei['year_ganzhi']}年生　{ziwei['wuxing_ju']}\n{note}"
        f"命宫：{ziwei['ming_gong']['ganzhi']}　身宫：{ziwei['shen_gong']['branch']}　"
        f"紫微在{ziwei['ziwei_branch']}　天府在{ziwei['tianfu_branch']}\n"
        f"生年四化：{sihua_line}\n\n"
        f"{grid}"
    )


def render_chart_md(chart: dict) -> str:
    """完整命盘 Markdown：八字 + 紫微。"""
    return render_bazi_md(chart["bazi"]) + "\n\n---\n\n" + render_ziwei_md(chart["ziwei"])


if __name__ == "__main__":
    from divination import paipan
    c = paipan({"date": "1995-08-15", "time": "06:30", "gender": "male"})
    print(render_chart_md(c))
