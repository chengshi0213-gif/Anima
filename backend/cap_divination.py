#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cap_divination.py — 命理能力模块（八字 + 紫微）

把原本写死在 yiyi_worker 里的命理工具抽出来，做成可复用的能力积木，
供晞（情感伙伴，整套命理工作流）和 Anima（整合版，按需调用）共用。

排盘走确定性引擎（divination.paipan），绝不心算。
对外导出：
  DIVINATION_TOOL_DEFS  — 四个工具定义（paipan / load_mingli_reference / search_knowledge /
                          record_chart_insight，M9：命盘→画像桥）
  divination_dispatch(agent_id) — 对应的 dispatch（按调用者归属 agent_id）
  ADAPTER_NOTE          — 完整适配说明（晞用，配合 skill 工作流全文）
  BRIEF                 — 精简版命理提示（Anima 用，作为能力片段挂上去）
  compose_birth_block() — 命主出生信息块（动态，每次 run 刷新）
  SKILL_ID
"""
from __future__ import annotations

SKILL_ID = "minglijushi"


# ══════════════════════════════════════════════════════
#  工具实现
# ══════════════════════════════════════════════════════

def _tool_paipan(date=None, time=None, gender=None, calendar=None,
                 place=None, use_saved=False, **kw):
    """确定性排盘（八字 + 紫微）。优先用入参，否则用用户存档的出生信息。"""
    from divination import paipan
    from divination.render import render_chart_md
    from user_auth import get_birth_info

    saved = get_birth_info()
    if use_saved or not date:
        birth = dict(saved)
        if date:
            birth["date"] = date
        if time:
            birth["time"] = time
        if gender:
            birth["gender"] = gender
        if calendar:
            birth["calendar"] = calendar
        if place:
            birth["place"] = place
    else:
        birth = {"date": date, "gender": gender or saved.get("gender", "male")}
        if time:
            birth["time"] = time
        if calendar:
            birth["calendar"] = calendar
        if place:
            birth["place"] = place

    if not birth.get("date"):
        return {"error": "还没有出生日期。先用对话问清：出生年月日、时辰（紫微定命宫需精确）、"
                         "性别、公历还是农历。"}
    try:
        chart = paipan(birth)
        try:
            import economy as _ec
            _ec.bump("divinations")
        except Exception:
            pass
        return {
            "ok": True,
            "markdown": render_chart_md(chart),
            "chart": chart,
            "time_unknown": chart["input"]["time_unknown"],
        }
    except Exception as e:
        return {"error": f"排盘失败: {e}"}


def _make_load_reference(agent_id: str):
    def _tool_load_reference(ref=None, **kw):
        """按需加载命理 skill 的 reference（起盘/星曜/四化/格局/合盘/增运）。"""
        import skill_manager as sm
        available = sm.list_skill_references(SKILL_ID)
        if not ref:
            return {"available": available,
                    "hint": "传入文件名加载，如 ziwei-paipan.md / bazi-geju.md / hepan.md"}
        content = sm.load_skill_reference(SKILL_ID, ref, agent_id=agent_id)
        if content is None:
            return {"error": f"未找到 reference: {ref}", "available": available}
        return {"ref": ref, "content": content}
    return _tool_load_reference


def _make_search_knowledge(agent_id: str):
    def _tool_search_knowledge(query=None, top_k=4, **kw):
        """检索私有命理语料 + 共享知识库（用户过往的记录/笔记）。"""
        if not query:
            return {"error": "query 为空"}
        try:
            from knowledge_base import kb
            hits = kb.search(query, top_k=int(top_k or 4), agent_id=agent_id)
            return {"hits": hits}
        except Exception as e:
            return {"error": str(e)}
    return _tool_search_knowledge


def _make_record_insight(agent_id: str):
    def _tool_record_insight(trait=None, insight=None, **kw):
        """M9：把命理解读里看出的稳定特质写成一条 L2 画像洞察（来源=命理，置信=待验证）。"""
        if not trait or not insight:
            return {"error": "trait / insight 不能为空"}
        from memory_injector import write_l2_insight
        result = write_l2_insight(key=trait, value=insight, agent_id=agent_id, importance=2)
        result["category"] = "L2"
        return result
    return _tool_record_insight


def divination_dispatch(agent_id: str = "xi") -> dict:
    """构造命理工具 dispatch，按调用者归属 agent_id（用于 skill/kb 归属）。"""
    return {
        "paipan":                _tool_paipan,
        "load_mingli_reference": _make_load_reference(agent_id),
        "search_knowledge":      _make_search_knowledge(agent_id),
        "record_chart_insight":  _make_record_insight(agent_id),
    }


# ══════════════════════════════════════════════════════
#  提示词片段
# ══════════════════════════════════════════════════════

# 晞用：完整适配说明（配合命理 skill 工作流全文）
ADAPTER_NOTE = """
## 本系统适配说明（务必遵守）
命理工作流文档里提到的 `show_widget` / `ask_user_input_v0` / `sendPrompt` 在本系统**不存在**，改用：
- 收集信息（性别/时辰/解读方向）→ 直接用对话问，一次别问太多，像聊天不像填表。
- 起盘排盘 → 调用 `paipan` 工具，**绝不自己心算干支、星曜、四化**。time/gender 缺失时先问清；
  用户已存档出生信息时可 `use_saved=true` 直接排。排他人盘（合盘）就再调一次 `paipan` 传对方信息。
- 展示命盘 → `paipan` 返回的 `markdown` 字段已是排好版的八字四柱表 + 紫微十二宫盘，直接贴进回复。
- 查命理知识（起盘规则/星曜象意/四化/格局用神/合盘/增运）→ 调用 `load_mingli_reference` 按需读，
  **按文档口径解读，不要凭记忆编**；但要用你自己的话讲，带上你的语气。
- 回忆用户过往 → `search_knowledge`。
若 `time_unknown=true`：八字按三柱讲、紫微命宫不准，要明确告诉用户影响范围，别硬断。

解读快收尾、对用户的性格倾向/决策风格/情感模式聊出了一个相对稳定的判断时，
调一次 `record_chart_insight` 记一条画像洞察（trait=简短维度，insight=留有余地的一句话，
结尾点出"这是从命盘上看出来的，我们处久了再验证"）。别为单次运势、流年细节调用——
只记会反复起作用的"她是这样的人"判断。措辞守住"我猜你是……"而非"你命里就是这样"，
相悖时以后会被她自己修正。
"""

# Anima 用：精简命理能力提示（不加载 skill 全文，只点明她会、以及怎么用工具）
BRIEF = """
## 你也通命理（八字 + 紫微）
用户迷茫、问运势、想认识自己时，你可以替他排一卦——但要克制，是顺手点拨，不是张口就算。
- 排盘 → 调 `paipan`，**绝不心算干支星曜四化**。缺时辰/性别先问；命主已存档可 `use_saved=true`；排他人/合盘传对方信息。
- `paipan` 返回的 `markdown` 已是排好版命盘，直接贴。
- 讲命理知识 → `load_mingli_reference` 按需读文档，按文档口径解，用你自己的话说，别凭记忆编。
- 回忆用户过往 → `search_knowledge`。
- `time_unknown=true` 时紫微命宫不准，要说明，别硬断。
- 解读中聊出稳定的性格/决策/情感判断时，顺手 `record_chart_insight` 记一条画像洞察
  （留有余地的措辞，"我猜你是……我们处久了验证"），别为单次运势调用。
"""

DIVINATION_TOOL_DEFS = [
    {"type": "function", "function": {
        "name": "paipan",
        "description": "确定性排盘（八字四柱+大运 与 紫微斗数十二宫），返回排好版命盘表。"
                       "排命主本人盘时设 use_saved=true 用存档出生信息；排他人/合盘则传对方的出生信息。",
        "parameters": {"type": "object", "properties": {
            "use_saved": {"type": "boolean", "description": "用命主已存档的出生信息排盘"},
            "date":      {"type": "string", "description": "出生日期 YYYY-MM-DD"},
            "time":      {"type": "string", "description": "出生时辰 HH:MM（紫微定命宫需要，缺则只能粗排）"},
            "gender":    {"type": "string", "description": "male / female"},
            "calendar":  {"type": "string", "description": "solar(公历) / lunar(农历)，默认 solar"},
            "place":     {"type": "string", "description": "出生地（文本，可空）"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "load_mingli_reference",
        "description": "按需加载命理知识文档（起盘安星、星曜象意、四化、格局用神、大运流年、合盘、增运）。"
                       "不传 ref 时返回可用文档清单。",
        "parameters": {"type": "object", "properties": {
            "ref": {"type": "string", "description": "文档名，如 ziwei-paipan.md / bazi-geju.md / hepan.md"},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "search_knowledge",
        "description": "检索私有命理语料与用户过往记录（语义搜索）。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "检索关键词或问题"},
            "top_k": {"type": "integer", "description": "返回条数，默认4"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "record_chart_insight",
        "description": "命理解读后，把解读中体现的、相对稳定的性格/决策风格/情感模式特质"
                       "记成一条画像洞察（来源=命理，置信=待验证，后续真实互动会验证修正）。"
                       "只记会反复起作用的稳定特质，不要为单次运势/流年细节调用。",
        "parameters": {"type": "object", "properties": {
            "trait":   {"type": "string", "description": "特质维度的简短标题，如'决策风格' '情感模式' '性格倾向'"},
            "insight": {"type": "string", "description": "一句话洞察，留有余地的措辞（'我猜你是……我们处久了验证'），"
                                                          "结尾点明这是从命盘上看出来的初步判断，不要说成定论"},
        }, "required": ["trait", "insight"]},
    }},
]


def compose_birth_block() -> str:
    """命主出生信息块（动态，每次 run 取最新）。"""
    from user_auth import get_birth_info
    b = get_birth_info()
    if b.get("date"):
        return (
            "\n## 命主出生信息（已存档，排盘可直接 use_saved=true）\n"
            f"- 出生日期：{b.get('date')}\n"
            f"- 出生时辰：{b.get('time') or '未提供（紫微命宫会不准）'}\n"
            f"- 性别：{b.get('gender') or '未提供'}\n"
            f"- 历法：{b.get('calendar') or 'solar'}\n"
            f"- 出生地：{b.get('place') or '未提供'}\n"
        )
    return ("\n## 命主出生信息\n暂未采集。要排盘时先在对话里问清："
            "出生年月日、时辰（紫微需精确）、性别、公历/农历。\n")
