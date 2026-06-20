#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
interpret.py v2 — 命盘解读引擎（八字 + 紫微）

确定性查表组装，不靠 LLM 即兴：底本 interpret_data.py 蒸馏自仓库已有命理语料。
v2 扩充：接入 bazi_enrich 算法层，八字从 4 段扩到 8-10 段，紫微从 5 段扩到 8-10 段。

入口：interpret_chart(chart) -> {"bazi":[section...], "ziwei":[section...]}
section = {"title": str, "body": str?}  或  {"title": str, "items": [str...]}
"""
from __future__ import annotations

from . import interpret_data as D
from .bazi_enrich import enrich_bazi, count_shishen

_MAIN = {"紫微", "天机", "太阳", "武曲", "天同", "廉贞", "天府",
         "太阴", "贪狼", "巨门", "天相", "天梁", "七杀", "破军"}
_GAN_WUXING = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
               "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
_GAN_YANG = {"甲": True, "乙": False, "丙": True, "丁": False, "戊": True,
             "己": False, "庚": True, "辛": False, "壬": True, "癸": False}
_SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
_KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}
# 十神归类：扶身（印·比劫） vs 耗身（食伤·财·官杀）
_FU = {"比肩", "劫财", "正印", "偏印"}
_HAO = {"食神", "伤官", "正财", "偏财", "正官", "七杀"}


def _d(name: str) -> dict:
    return getattr(D, name, {}) or {}


def _ds(name: str) -> str:
    v = getattr(D, name, "")
    return v if isinstance(v, str) else ""


def _shishen(dm: str, target: str) -> str:
    """命主日主 dm 看 target 天干，得十神名。"""
    a, b = _GAN_WUXING.get(dm), _GAN_WUXING.get(target)
    if not a or not b:
        return ""
    same = _GAN_YANG.get(dm) == _GAN_YANG.get(target)
    if a == b:
        return "比肩" if same else "劫财"
    if _SHENG.get(a) == b:
        return "食神" if same else "伤官"
    if _KE.get(a) == b:
        return "偏财" if same else "正财"
    if _KE.get(b) == a:
        return "七杀" if same else "正官"
    if _SHENG.get(b) == a:
        return "偏印" if same else "正印"
    return ""


def _xiyong(shishen: str, ws_level: str) -> str:
    """据日主旺衰判断某十神运是「喜」「忌」还是「平」（扶抑法）。"""
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


# ── 八字解读 ──────────────────────────────────────────────
def bazi_reading(b: dict) -> list[dict]:
    if not b:
        return []
    out: list[dict] = []
    dm = b.get("day_master", "")
    dm_wx = b.get("day_master_wuxing", "") or _GAN_WUXING.get(dm, "")
    pillars = b.get("pillars", {})

    enrichment = enrich_bazi(b)

    # 1) 日主性格（展开为多维度）
    dm_info = _d("DAY_MASTER").get(dm)
    if dm_info:
        if isinstance(dm_info, dict):
            body = (f"「{dm_info.get('nature', '')}」——{dm_info.get('character', '')} "
                    f"{dm_info.get('relationship', '')} {dm_info.get('advice', '')}")
        else:
            body = str(dm_info)
        out.append({"title": f"日主 · {dm}（{dm_wx}）", "body": body})

    # 2) 格局定性
    geju = enrichment.get("geju", {})
    geju_name = geju.get("name", "")
    if geju_name:
        geju_desc = _d("GEJU_DESC").get(geju_name, {})
        basis = geju.get("basis", "")
        tougan = geju.get("tougan", [])
        parts = [f"月令取{basis}为格，定为「{geju_name}」。"]
        if tougan:
            parts.append(f"格神在{'、'.join(tougan)}透干，格局力量更强。")
        if isinstance(geju_desc, dict):
            parts.append(geju_desc.get("summary", ""))
            parts.append(geju_desc.get("detail", ""))
            if geju_desc.get("like"):
                parts.append(f"此格喜：{geju_desc['like']}。")
            if geju_desc.get("dislike"):
                parts.append(f"此格忌：{geju_desc['dislike']}。")
        elif geju_desc:
            parts.append(str(geju_desc))
        out.append({"title": f"格局 · {geju_name}", "body": " ".join(p for p in parts if p)})

    # 3) 旺衰评估
    ws = enrichment.get("wangshuai", {})
    ws_level = ws.get("level", "")
    if ws_level and ws_level != "未知":
        ws_desc = _d("WANGSHUAI_DESC").get(ws_level, "")
        details = ws.get("details", [])
        score = ws.get("score", 0)
        body = f"日主{dm}身强弱评估：「{ws_level}」（综合评分 {score}）。"
        if details:
            body += f"依据：{'；'.join(details)}。"
        if ws_desc:
            body += f" {ws_desc}"
        out.append({"title": f"旺衰 · {ws_level}", "body": body})

    # 4) 四柱概览
    pillar_items = []
    pillar_domain = _d("PILLAR_DOMAIN")
    for pos, zh in [("year", "年柱"), ("month", "月柱"), ("day", "日柱"), ("time", "时柱")]:
        p = pillars.get(pos, {})
        if not p.get("ganzhi"):
            continue
        gan = p.get("gan", "")
        zhi = p.get("zhi", "")
        ss_gan = p.get("shishen_gan", "")
        nayin = p.get("nayin", "")
        hide_gan = p.get("hide_gan", [])
        parts = [f"{zh} {p.get('ganzhi', '')}"]
        if nayin:
            parts.append(f"纳音「{nayin}」")
        if ss_gan and pos != "day":
            parts.append(f"天干十神为{ss_gan}")
        if hide_gan:
            parts.append(f"地支藏干{'·'.join(hide_gan)}")
        domain = pillar_domain.get(pos, "")
        if domain:
            parts.append(f"— {domain}")
        pillar_items.append("；".join(parts))
    if pillar_items:
        out.append({"title": "四柱概览", "items": pillar_items})

    # 5) 五行平衡
    wx_info = enrichment.get("wuxing", {})
    wx_count = wx_info.get("count", {})
    if wx_count:
        missing = wx_info.get("missing", [])
        strongest = wx_info.get("strongest", "")
        weakest = wx_info.get("weakest", "")
        dist = "、".join(f"{k}{v}" for k, v in wx_count.items())
        parts = [f"五行分布：{dist}。"]
        if missing:
            parts.append(f"五行缺{'、'.join(missing)}——命中{'、'.join(missing)}的能量不足，可从行业、方位、色彩上适度补充。")
        parts.append(f"最旺五行为{strongest}，最弱为{weakest}。")
        industry = _d("WUXING_INDUSTRY").get(dm_wx, "")
        if industry:
            parts.append(f"日主属{dm_wx}，行业上可往：{industry}。")
        out.append({"title": f"五行平衡 · {dm_wx}", "body": " ".join(parts)})

    # 6) 月令调候
    month = pillars.get("month", {})
    mz = month.get("zhi", "")
    tiaohou = _d("TIAOHOU").get(mz)
    if tiaohou:
        out.append({"title": "调候 · 寒暖燥湿", "body": tiaohou})

    # 7) 干支关系
    gan_rels = enrichment.get("gan_relations", [])
    zhi_rels = enrichment.get("zhi_relations", [])
    rel_desc = _d("ZHI_RELATION_DESC")
    rel_items = []
    for r in gan_rels:
        desc = rel_desc.get("五合", "")
        line = f"天干{r.get('type', '')}：{r.get('gans', '')}（{r.get('positions', '')}）{r.get('result', '')}"
        if desc:
            line += f"。{desc}"
        rel_items.append(line)
    for r in zhi_rels:
        rtype = r.get("type", "")
        desc = rel_desc.get(rtype, "")
        line = f"地支{rtype}：{r.get('zhis', '')}（{r.get('positions', '')}）"
        if r.get("result"):
            line += r["result"]
        if r.get("desc"):
            line += f"（{r['desc']}）"
        if desc:
            line += f"。{desc}"
        rel_items.append(line)
    if rel_items:
        out.append({"title": "干支关系 · 刑冲合会", "items": rel_items})

    # 8) 十二长生
    cs = enrichment.get("changsheng", {})
    cs_desc = _d("CHANGSHENG_DESC")
    if cs:
        cs_items = []
        pos_zh = {"year": "年支", "month": "月支", "day": "日支", "time": "时支"}
        for pos in ("year", "month", "day", "time"):
            state = cs.get(pos, "")
            if state:
                desc = cs_desc.get(state, "")
                line = f"{pos_zh.get(pos, pos)}处「{state}」之位"
                if desc:
                    line += f"——{desc}"
                cs_items.append(line)
        if cs_items:
            out.append({"title": f"十二长生 · {dm}的生命周期", "items": cs_items})

    # 9) 月令十神
    ss = month.get("shishen_gan", "")
    ss_info = _d("SHISHEN").get(ss)
    if ss_info:
        if isinstance(ss_info, dict):
            body = (f"月令天干十神为「{ss}」——{ss_info.get('trait', '')}；"
                    f"偏向{ss_info.get('domain', '')}的路子。"
                    f"{ss_info.get('detail', '')}")
        else:
            body = str(ss_info)
        out.append({"title": f"月令十神 · {ss}", "body": body})

    # 10) 大运 · 逐运详解（十神 + 喜忌 + 当前所在 + 主题）
    dayun = b.get("dayun", [])
    if dayun:
        from datetime import date as _date
        ws_level = ws.get("level", "") if isinstance(ws, dict) else ""
        cur_year = _date.today().year
        # 定位当前所在大运：start_year <= 今年 < 下一步 start_year
        cur_idx = -1
        for i, dy in enumerate(dayun):
            sy = dy.get("start_year")
            ny = dayun[i + 1].get("start_year") if i + 1 < len(dayun) else 9999
            if isinstance(sy, int) and sy <= cur_year < (ny if isinstance(ny, int) else 9999):
                cur_idx = i
                break
        dy_items = []
        for i, dy in enumerate(dayun[:9]):
            gz = dy.get("ganzhi", "")
            gan, zhi = gz[:1], gz[1:2]
            ss_g = _shishen(dm, gan)
            xy = _xiyong(ss_g, ws_level)
            age = dy.get("start_age", "")
            nxt_age = dayun[i + 1].get("start_age") if i + 1 < len(dayun) else None
            end_age = (nxt_age - 1) if isinstance(nxt_age, int) else (
                age + 9 if isinstance(age, int) else "")
            theme = _d("DAYUN_SHISHEN").get(ss_g, "")
            mark = "　← 你正走这一步" if i == cur_idx else ""
            line = f"{age}–{end_age}岁 {gz}（{ss_g or '—'}运 · {xy}）{mark}"
            if theme:
                line += f"：{theme}"
            dy_items.append(line)
        body_parts = [_ds("DAYUN_INTRO")]
        if cur_idx >= 0:
            cur = dayun[cur_idx]
            cgz = cur.get("ganzhi", "")
            css = _shishen(dm, cgz[:1])
            cxy = _xiyong(css, ws_level)
            body_parts.append(
                f"你目前正走「{cgz}」大运（{cur.get('start_age')}岁起，{css or '—'}运）——"
                f"{_d('DAYUN_XIYONG').get(cxy, '')}")
        else:
            body_parts.append("（按公历年份，你尚未起运或已过完所排大运，以下逐运排开供参看。）")
        out.append({"title": "大运 · 十年一运", "body": " ".join(p for p in body_parts if p),
                    "items": dy_items})

    if b.get("time_unknown"):
        out.append({"title": "提醒", "body": "时辰未知，时柱按午时近似，关于晚年与子女、深层性格的判断请打折看。"})
    return out


# ── 紫微解读 ──────────────────────────────────────────────
def _palace_of_star(palaces: list[dict], star: str) -> dict | None:
    for p in palaces:
        if any(s.get("name") == star for s in p.get("stars", [])):
            return p
    return None


def _opposite_palace(palaces: list[dict], pal: dict) -> dict | None:
    idx = pal.get("branch_index")
    if idx is None:
        return None
    return next((p for p in palaces if p.get("branch_index") == (idx + 6) % 12), None)


def _axis_summary(byname: dict, palace_names: list[str]) -> list[str]:
    items = []
    for nm in palace_names:
        p = byname.get(nm)
        if p:
            ms = [s["name"] for s in p.get("stars", []) if s.get("name") in _MAIN]
            items.append(f"{nm}（{p.get('branch', '')}）：{'、'.join(ms) or '借对宫'}")
    return items


def ziwei_reading(z: dict) -> list[dict]:
    if not z:
        return []
    out: list[dict] = []
    palaces = z.get("palaces", [])
    byname = {p.get("name"): p for p in palaces}
    palace_axis = _d("PALACE_AXIS")

    # 1) 命宫主星象意（含 in_ming 深解）
    ming = byname.get("命宫")
    if ming:
        majors = [s["name"] for s in ming.get("stars", []) if s.get("name") in _MAIN]
        if majors:
            lines = []
            for st in majors:
                info = _d("MAIN_STAR").get(st)
                if info:
                    line = (f"【{st}】{info.get('core', '')}。"
                            f"{info.get('person', '')} "
                            f"长处：{info.get('merit', '')} "
                            f"注意：{info.get('flaw', '')}")
                    if info.get("in_ming"):
                        line += f" ⸺ {info['in_ming']}"
                    lines.append(line)
                    lines.append(f"适合方向：{info.get('career', '')}")
            body = "\n".join(lines)
            combo = _d("DOUBLE_STAR").get("|".join(sorted(majors[:2]))) if len(majors) >= 2 else None
            if combo:
                body += f"\n\n【{'·'.join(majors[:2])}双星】{combo}"
            out.append({"title": f"命宫主星 · {'·'.join(majors)}", "body": body})
        else:
            opp = _opposite_palace(palaces, ming)
            opp_majors = [s["name"] for s in (opp or {}).get("stars", []) if s.get("name") in _MAIN]
            tip = f"对宫为{'、'.join(opp_majors)}，借入参看" if opp_majors else "需看三方四正会照"
            out.append({"title": "命宫 · 空宫", "body": f"命宫无主星，性情较随境而转、可塑性强；{tip}。"})

    # 2) 命宫辅煞
    if ming:
        aux = [s["name"] for s in ming.get("stars", []) if s.get("name") in _d("AUX_STAR")]
        if aux:
            notes = [f"{a}——{_d('AUX_STAR').get(a, '')}" for a in aux]
            out.append({"title": "命宫辅煞", "items": notes})

    # 3) 格局判定（吉凶格）
    if ming:
        majors_set = {s["name"] for s in ming.get("stars", []) if s.get("name") in _MAIN}
        all_stars = {s["name"] for s in ming.get("stars", [])}
        ge_items = []
        for name, desc in _d("GE_GOOD").items():
            ge_items.append(f"可能吉格「{name}」：{desc}（需综合三方四正确认）")
        for name, desc in _d("GE_BAD").items():
            ge_items.append(f"需注意凶格「{name}」：{desc}")
        if ge_items:
            out.append({"title": "参考格局", "items": ge_items[:4]})

    # 4) 生年四化落宫
    sihua_items = []
    for k, star in (z.get("sihua") or {}).items():
        pal = _palace_of_star(palaces, star)
        if pal:
            pal_name = pal.get("name", "")
            inpal = _d("SIHUA_IN_PALACE").get(k, {}).get(pal_name)
            meaning = _d("SIHUA_MEANING").get(k, "")
            line = f"{k}（{star}）落「{pal_name}」"
            if inpal:
                line += f"：{inpal}"
            elif meaning:
                line += f"：{meaning}"
            sihua_items.append(line)
    if sihua_items:
        out.append({"title": "生年四化 · 落宫", "items": sihua_items})

    # 5) 事业主轴 命财官迁
    axis_items = _axis_summary(byname, ["命宫", "财帛", "官禄", "迁移"])
    if axis_items:
        desc = palace_axis.get("命财官迁", "")
        section = {"title": "事业主轴 · 命财官迁", "items": axis_items}
        if desc:
            section["body"] = desc
        out.append(section)

    # 6) 人际关系轴 夫子奴友
    axis_items2 = _axis_summary(byname, ["夫妻", "子女", "交友"])
    if axis_items2:
        desc2 = palace_axis.get("夫子奴友", "")
        section2 = {"title": "人际关系 · 夫子交友", "items": axis_items2}
        if desc2:
            section2["body"] = desc2
        out.append(section2)

    # 7) 生活底色 父疾福田
    axis_items3 = _axis_summary(byname, ["父母", "疾厄", "福德", "田宅"])
    if axis_items3:
        desc3 = palace_axis.get("父疾福田", "")
        section3 = {"title": "生活底色 · 父疾福田", "items": axis_items3}
        if desc3:
            section3["body"] = desc3
        out.append(section3)

    # 8) 身宫
    shen_branch = (z.get("shen_gong") or {}).get("branch")
    shen_pal = next((p for p in palaces if p.get("branch") == shen_branch), None)
    if shen_pal:
        ms = [s["name"] for s in shen_pal.get("stars", []) if s.get("name") in _MAIN]
        body = (f"身宫落「{shen_pal.get('name')}」（{shen_branch}）"
                f"{'，主星' + '、'.join(ms) if ms else ''}。"
                f"身宫是后天修炼的方向——30岁后逐渐显化、影响力与命宫平分秋色。"
                f"身宫落何宫即你后天最用力的人生领域。")
        out.append({"title": "身宫 · 后天着力", "body": body})

    # 9) 大限提示（第一步大限）
    dalian = z.get("dalian", [])
    if dalian and len(dalian) >= 2:
        first = dalian[0]
        current_hint = f"第一步大限（{first.get('range', '')}）：起于{first.get('branch', '')}宫"
        out.append({"title": "大限起步", "body": current_hint})

    if z.get("time_unknown"):
        out.append({"title": "提醒", "body": "时辰未知，命宫与十二宫定位仅供参考，命宫主星可能有偏差。"})
    return out


# ── 结构化可视化数据（供前端三大招牌图：五行环/十神占比/大运评分）──
_SS_CAT = {"比肩": "比劫", "劫财": "比劫", "食神": "食伤", "伤官": "食伤",
           "正财": "财", "偏财": "财", "正官": "官", "七杀": "官",
           "正印": "印", "偏印": "印"}
_CAT_PAIR = {"比劫": "比肩劫财", "食伤": "食神伤官", "财": "正财偏财",
             "官": "正官七杀", "印": "正印偏印"}
_SHENG_INV = {"火": "木", "土": "火", "金": "土", "水": "金", "木": "水"}  # 谁生我


def _element_cat(dm_wx: str, el: str) -> str:
    """某五行 el 相对日主 dm_wx 的十神大类。"""
    if not dm_wx or not el:
        return ""
    if el == dm_wx:
        return "比劫"
    if _SHENG.get(dm_wx) == el:
        return "食伤"
    if _KE.get(dm_wx) == el:
        return "财"
    if _KE.get(el) == dm_wx:
        return "官"
    if _SHENG.get(el) == dm_wx:
        return "印"
    return ""


def _yongshen_wuxing(dm_wx: str, ws_level: str) -> str:
    if ws_level in ("偏弱", "极弱"):
        return _SHENG_INV.get(dm_wx, dm_wx)
    if ws_level in ("偏旺", "极旺"):
        return _SHENG.get(dm_wx, dm_wx)
    return dm_wx


def _dayun_score(ss: str, xy: str) -> int:
    base = {"喜": 80, "平": 62, "忌": 46}.get(xy, 60)
    nudge = {"正财": 6, "偏财": 4, "正官": 5, "食神": 6, "正印": 4,
             "比肩": 2, "劫财": -2, "伤官": 0, "七杀": -2, "偏印": 0}.get(ss, 0)
    return max(20, min(99, base + nudge))


def dayun_scored(b: dict) -> list[dict]:
    """大运评分时间轴：逐运 干支/十神/喜忌/分数/诗题/是否当前。"""
    from datetime import date as _date
    dm = b.get("day_master", "")
    ws_level = (enrich_bazi(b).get("wangshuai") or {}).get("level", "")
    dayun = b.get("dayun", [])
    cur_year = _date.today().year
    cur_idx = -1
    for i, dy in enumerate(dayun):
        sy = dy.get("start_year")
        ny = dayun[i + 1].get("start_year") if i + 1 < len(dayun) else 9999
        if isinstance(sy, int) and sy <= cur_year < (ny if isinstance(ny, int) else 9999):
            cur_idx = i
            break
    out = []
    for i, dy in enumerate(dayun):
        gz = dy.get("ganzhi", "")
        gan, zhi = gz[:1], gz[1:2]
        ss = _shishen(dm, gan)
        xy = _xiyong(ss, ws_level)
        cat = _SS_CAT.get(ss, "比劫")
        age = dy.get("start_age", "")
        nxt = dayun[i + 1].get("start_age") if i + 1 < len(dayun) else None
        end_age = (nxt - 1) if isinstance(nxt, int) else (age + 9 if isinstance(age, int) else "")
        out.append({
            "start_age": age, "end_age": end_age, "ganzhi": gz, "gan": gan, "zhi": zhi,
            "shishen": ss, "xiyong": xy, "score": _dayun_score(ss, xy),
            "title": _d("DAYUN_TITLE").get(cat, {}).get(xy, ""),
            "current": i == cur_idx,
        })
    return out


def _viz_data(b: dict) -> dict:
    if not b or not b.get("day_master"):
        return {}
    dm = b.get("day_master", "")
    dm_wx = b.get("day_master_wuxing", "") or _GAN_WUXING.get(dm, "")
    e = enrich_bazi(b)
    ws = e.get("wangshuai", {})
    ws_level = ws.get("level", "")
    wx = e.get("wuxing", {})
    counts = wx.get("count", {})
    total = sum(counts.values()) or 1.0
    yong = _yongshen_wuxing(dm_wx, ws_level)
    elements = []
    for el in ("木", "火", "土", "金", "水"):
        v = counts.get(el, 0)
        cat = _element_cat(dm_wx, el)
        elements.append({
            "wuxing": el, "value": v, "percent": round(v / total * 100),
            "cat": cat, "shishen_pair": _CAT_PAIR.get(cat, ""),
            "is_day": el == dm_wx, "is_yong": el == yong,
        })
    return {
        "wuxing": {
            "elements": elements, "day_master": dm, "day_master_wx": dm_wx,
            "yongshen": yong, "missing": wx.get("missing", []),
            "strongest": wx.get("strongest", ""), "weakest": wx.get("weakest", ""),
        },
        "shishen": count_shishen(b),
        "dayun": dayun_scored(b),
        "wangshuai": {"level": ws_level, "score": ws.get("score", 0)},
        "geju": e.get("geju", {}),
    }


def interpret_chart(chart: dict) -> dict:
    """命盘 → 结构化解读 + 可视化数据。供前端卡片/招牌图渲染。"""
    b = chart.get("bazi", {})
    return {
        "bazi": bazi_reading(b),
        "ziwei": ziwei_reading(chart.get("ziwei", {})),
        "viz": _viz_data(b),
    }


if __name__ == "__main__":
    import json
    from divination import paipan
    c = paipan({"date": "2002-02-24", "time": "07:30", "gender": "male"})
    print(json.dumps(interpret_chart(c), ensure_ascii=False, indent=2))
