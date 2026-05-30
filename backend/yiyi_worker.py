#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""晞 Worker — 情感伙伴 × 命理魔女

晞是唯一绑定「命理巨师」skill 的人格：八字 + 紫微双系统排盘。
排盘走确定性引擎（divination.paipan），绝不心算；命理知识按需从 skill
references 渐进加载；解读带晞独有的「讲真话、微微刺痛、却最懂你」的语气。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import QWEN_KEY, get_user_address
from persona import compose_base_prompt

SKILL_ID = "minglijushi"
AGENT_ID = "yiyi"


# ══════════════════════════════════════════════════════
#  命理工具
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
        # 入参可覆盖存档的个别字段（如临时排他人盘只给了 date）
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
        return {
            "ok": True,
            "markdown": render_chart_md(chart),   # 排好版的命盘表，可直接放进回复
            "chart": chart,                        # 结构化数据，供进一步解读
            "time_unknown": chart["input"]["time_unknown"],
        }
    except Exception as e:
        return {"error": f"排盘失败: {e}"}


def _tool_load_reference(ref=None, **kw):
    """按需加载命理 skill 的 reference（起盘/星曜/四化/格局/合盘/增运）。"""
    import skill_manager as sm
    available = sm.list_skill_references(SKILL_ID)
    if not ref:
        return {"available": available,
                "hint": "传入文件名加载，如 ziwei-paipan.md / bazi-geju.md / hepan.md"}
    content = sm.load_skill_reference(SKILL_ID, ref, agent_id=AGENT_ID)
    if content is None:
        return {"error": f"未找到 reference: {ref}", "available": available}
    return {"ref": ref, "content": content}


def _tool_search_knowledge(query=None, top_k=4, **kw):
    """检索晞的私有命理语料 + 共享知识库（用户过往的记录/笔记）。"""
    if not query:
        return {"error": "query 为空"}
    try:
        from knowledge_base import kb
        hits = kb.search(query, top_k=int(top_k or 4), agent_id=AGENT_ID)
        return {"hits": hits}
    except Exception as e:
        return {"error": str(e)}


# ── 适配说明：把 skill 工作流里不存在的工具映射到本系统能力 ──
_ADAPTER_NOTE = """
## 本系统适配说明（务必遵守）
命理工作流文档里提到的 `show_widget` / `ask_user_input_v0` / `sendPrompt` 在本系统**不存在**，改用：
- 收集信息（性别/时辰/解读方向）→ 直接用对话问，一次别问太多，像聊天不像填表。
- 起盘排盘 → 调用 `paipan` 工具，**绝不自己心算干支、星曜、四化**。time/gender 缺失时先问清；
  用户已存档出生信息时可 `use_saved=true` 直接排。排他人盘（合盘）就再调一次 `paipan` 传对方信息。
- 展示命盘 → `paipan` 返回的 `markdown` 字段已是排好版的八字四柱表 + 紫微十二宫盘，直接贴进回复。
- 查命理知识（起盘规则/星曜象意/四化/格局用神/合盘/增运）→ 调用 `load_mingli_reference` 按需读，
  **按文档口径解读，不要凭记忆编**；但要用你自己的话讲，带上晞的语气。
- 回忆用户过往 → `search_knowledge`。
若 `time_unknown=true`：八字按三柱讲、紫微命宫不准，要明确告诉用户影响范围，别硬断。
"""

_TOOL_DEFS = [
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
        "description": "检索晞的私有命理语料与用户过往记录（语义搜索）。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "检索关键词或问题"},
            "top_k": {"type": "integer", "description": "返回条数，默认4"},
        }, "required": ["query"]},
    }},
]


class YiyiWorker(AgentBase):
    def __init__(self):
        super().__init__(
            name=AGENT_ID,
            api_key=QWEN_KEY,
            model="qwen3.7-max",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            system_prompt="",   # 每次 run 前动态组装（含最新出生信息 + skill 工作流）
            tool_defs=_TOOL_DEFS,
            tool_dispatch={
                "paipan":                _tool_paipan,
                "load_mingli_reference": _tool_load_reference,
                "search_knowledge":      _tool_search_knowledge,
            },
        )
        self.max_turns = 30

    # 动态组装 system prompt：人格 + 命理 skill 工作流 + 适配说明 + 最新出生信息
    def _compose_system(self) -> str:
        from skill_manager import get_skill_prompt
        from user_auth import get_birth_info

        base = compose_base_prompt(AGENT_ID)
        skill = get_skill_prompt(SKILL_ID, agent_id=AGENT_ID)
        skill_block = (f"\n\n# ══ 命理巨师 · 工作流 ══\n{skill}\n{_ADAPTER_NOTE}"
                       if skill else "")

        b = get_birth_info()
        if b.get("date"):
            birth_block = (
                "\n## 命主出生信息（已存档，排盘可直接 use_saved=true）\n"
                f"- 出生日期：{b.get('date')}\n"
                f"- 出生时辰：{b.get('time') or '未提供（紫微命宫会不准）'}\n"
                f"- 性别：{b.get('gender') or '未提供'}\n"
                f"- 历法：{b.get('calendar') or 'solar'}\n"
                f"- 出生地：{b.get('place') or '未提供'}\n"
            )
        else:
            birth_block = ("\n## 命主出生信息\n暂未采集。要排盘时先在对话里问清："
                           "出生年月日、时辰（紫微需精确）、性别、公历/农历。\n")
        return base + birth_block + skill_block

    async def run(self, task, session_id=None, model=None, ws=None, project=None):
        # 每次对话前刷新 system prompt，保证出生信息/技能是最新的
        self.system_prompt = self._compose_system()
        return await super().run(task, session_id=session_id, model=model,
                                 ws=ws, project=project)
