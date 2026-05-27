#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anima — 日报 / 周报生成器
ColaOS 风格：温暖、有记忆、有观察，不是冷冰冰的统计
"""
import json
import sqlite3
import asyncio
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional

from config import DATA_DIR, SESSIONS_DB, DEEPSEEK_KEY, KIMI_KEY, QWEN_KEY, OPENAI_KEY

REPORTS_DIR  = DATA_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

SENT_LOG     = REPORTS_DIR / "sent_log.json"   # 记录已发送的报告

AGENT_DISPLAY = {
    "xi":       ("👩‍💼", "Anima"),
    "yiyi":     ("🌸",  "晞"),
    "tianyuan": ("🏢",  "陶朱"),
    "shoucang":  ("🎓",  "守藏"),
    "executor": ("⚡",  "执行者"),
    "writer":   ("✍️",  "写手"),
    "reader":   ("📖",  "阅读者"),
    "critic":   ("🔍",  "评审"),
}

WEEKDAYS_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
MONTHS_ZH   = ["一月","二月","三月","四月","五月","六月",
                "七月","八月","九月","十月","十一月","十二月"]


# ── 发送状态管理 ────────────────────────────────────────
def _load_sent_log() -> dict:
    if SENT_LOG.exists():
        try:
            return json.loads(SENT_LOG.read_text("utf-8"))
        except Exception:
            pass
    return {}


def _mark_sent(report_type: str, key: str):
    log = _load_sent_log()
    log[f"{report_type}:{key}"] = datetime.now().isoformat()
    SENT_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), "utf-8")


def should_send_daily() -> bool:
    """今天是否还没发过日报"""
    log = _load_sent_log()
    today = date.today().isoformat()
    return f"daily:{today}" not in log


def should_send_weekly() -> bool:
    """本周一是否还没发过周报，且今天是周一"""
    if date.today().weekday() != 0:   # 0=周一
        return False
    log = _load_sent_log()
    monday = date.today().isoformat()
    return f"weekly:{monday}" not in log


# ── 数据查询 ────────────────────────────────────────────
def _query_sessions(since_ts: float, until_ts: float = None) -> list[dict]:
    """从 sessions.db 查询指定时间段内的对话"""
    if not SESSIONS_DB.exists():
        return []
    until_ts = until_ts or datetime.now().timestamp()
    try:
        conn = sqlite3.connect(str(SESSIONS_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM sessions WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp",
            (since_ts, until_ts)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f"[Report] DB query error: {e}")
        return []


def _query_messages(session_id: str) -> list[dict]:
    """查询某会话的消息"""
    if not SESSIONS_DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(SESSIONS_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def _build_stats(sessions: list[dict]) -> dict:
    """构建统计数据"""
    by_agent   = {}
    by_hour    = {h: 0 for h in range(24)}
    by_day     = {}
    total_msgs = 0

    for s in sessions:
        agent = s.get("agent", "xi")
        by_agent[agent] = by_agent.get(agent, 0) + 1
        ts  = s.get("timestamp", 0)
        dt  = datetime.fromtimestamp(ts)
        by_hour[dt.hour] = by_hour.get(dt.hour, 0) + 1
        day_key = dt.strftime("%Y-%m-%d")
        by_day[day_key]  = by_day.get(day_key, 0) + 1
        msgs = _query_messages(s.get("session_id",""))
        total_msgs += len(msgs)

    return {
        "total_sessions": len(sessions),
        "total_messages":  total_msgs,
        "by_agent":        by_agent,
        "by_hour":         by_hour,
        "by_day":          by_day,
        "most_active_agent": max(by_agent, key=by_agent.get) if by_agent else "xi",
        "peak_hour": max(by_hour, key=by_hour.get) if any(by_hour.values()) else 10,
    }


def _extract_topics(sessions: list[dict], max_sessions: int = 10) -> list[str]:
    """从最近 N 个会话提取摘要（用于情感文字生成）"""
    topics = []
    for s in sessions[-max_sessions:]:
        summary = s.get("summary", "") or s.get("title", "")
        if summary and len(summary) > 5:
            topics.append(summary[:100])
    return topics


# ── 情感文字生成 ────────────────────────────────────────
def _pick_api_key():
    for k in [DEEPSEEK_KEY, KIMI_KEY, QWEN_KEY, OPENAI_KEY]:
        if k and not k.startswith("sk-xxx"):
            return k
    return None


def _generate_warm_text_sync(prompt: str) -> str:
    """同步调用 LLM 生成情感文字（无流式）"""
    key = _pick_api_key()
    if not key:
        return ""
    import urllib.request
    import json as _json

    # 根据可用 key 选接口
    if DEEPSEEK_KEY and not DEEPSEEK_KEY.startswith("sk-xxx"):
        url   = "https://api.deepseek.com/chat/completions"
        model = "deepseek-chat"
        api_key = DEEPSEEK_KEY
    elif KIMI_KEY and not KIMI_KEY.startswith("sk-xxx"):
        url   = "https://api.moonshot.cn/v1/chat/completions"
        model = "moonshot-v1-8k"
        api_key = KIMI_KEY
    else:
        return ""

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600,
        "temperature": 0.9,
    }
    try:
        data = _json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type":"application/json","Authorization":f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = _json.loads(resp.read())
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[Report] LLM error: {e}")
        return ""


# ── 日报 ────────────────────────────────────────────────
def _get_membership_notice() -> dict | None:
    """生成会员到期提醒（剩余 ≤14 天时提醒）"""
    try:
        from membership import get_membership
        m = get_membership()
        if m.get("active") and m.get("tier") == "pro":
            days = m.get("days_left", 999)
            if days <= 14:
                return {
                    "warning": True,
                    "days_left": days,
                    "expires": m.get("expires", ""),
                    "message": f"⚠️ Pro 会员将在 {days} 天后到期（{m.get('expires','')}），届时 22 个 Pro Skill 将被锁定。",
                }
            return {"warning": False, "days_left": days, "tier": "pro"}
        return {"warning": False, "tier": "free"}
    except Exception:
        return None


def generate_daily_report() -> dict:
    """生成昨日日报"""
    yesterday_start = datetime.combine(date.today() - timedelta(days=1), datetime.min.time())
    yesterday_end   = datetime.combine(date.today(), datetime.min.time())
    sessions = _query_sessions(yesterday_start.timestamp(), yesterday_end.timestamp())
    stats    = _build_stats(sessions)
    topics   = _extract_topics(sessions)

    today      = date.today()
    weekday_zh = WEEKDAYS_ZH[today.weekday()]
    date_str   = f"{today.month}月{today.day}日 {weekday_zh}"

    # 读取 Skill 升级记录
    from skill_manager import list_skills
    skills = list_skills()
    recent_upgrades = [
        s for s in skills
        if s.get("last_improved") == (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    ]

    # 读取 Vault 用户档案（让 Anima 认识这个人）
    user_profile_snippet = ""
    try:
        from memory_injector import get_memory_injection
        vault_ctx = get_memory_injection("xi")
        # 截取前 300 字作为人物背景
        if vault_ctx and len(vault_ctx) > 20:
            user_profile_snippet = vault_ctx[:300]
    except Exception:
        pass

    # 生成情感文字
    if sessions:
        topic_text = "、".join(topics[:3]) if topics else "各种话题"
        most_agent = AGENT_DISPLAY.get(stats["most_active_agent"],("🤖","未知"))[1]
        profile_section = f"\n用户背景信息：\n{user_profile_snippet}\n" if user_profile_snippet else ""
        llm_prompt = f"""你是 Anima，用户最信任的 AI 伙伴。
今天是{date_str}，请写一段日报开场白（150字以内）。
{profile_section}
昨天的情况：
- 共进行了 {stats['total_sessions']} 次对话
- 主要聊了：{topic_text}
- 最常用的助手：{most_agent}
- 最活跃时段：{stats['peak_hour']}:00 左右

风格要求：
1. 像一个真正认识你的朋友，不是 AI 助手
2. 如果知道用户背景，用姓名或具体细节让文字更有温度
3. 提到具体的对话内容（不要泛泛而谈）
4. 表达一个真实的观察或感受
5. 自然引出今天
6. 不要用「昨日共X次对话」这种机器人语言
7. 第一人称，温暖，有点文艺感"""
        warm_text = _generate_warm_text_sync(llm_prompt)
    else:
        warm_text = f"今天是{date_str}。昨天我们没有聊什么，但今天又是新的开始。你准备好了吗？"

    # 图表数据
    chart_data = {
        "type":     "daily",
        "timeline": [{"hour": h, "count": stats["by_hour"][h]} for h in range(6, 24)],
        "by_agent": [
            {"agent": k, "name": AGENT_DISPLAY.get(k,("🤖",k))[1],
             "icon":  AGENT_DISPLAY.get(k,("🤖",k))[0], "count": v}
            for k, v in stats["by_agent"].items()
        ],
    }

    report = {
        "type":       "daily",
        "date":       date_str,
        "date_iso":   today.isoformat(),
        "warm_text":  warm_text,
        "stats":      stats,
        "chart_data": chart_data,
        "topics":     topics[:5],
        "skill_upgrades": [
            {"name": s.get("name",""), "version": s.get("version",1),
             "icon": s.get("icon","⚡")}
            for s in recent_upgrades
        ],
        "membership": _get_membership_notice(),
        "generated_at": datetime.now().isoformat(),
    }

    # 保存 + 标记已发送
    out = REPORTS_DIR / f"daily_{today.isoformat()}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    _mark_sent("daily", today.isoformat())
    return report


# ── 周报 ────────────────────────────────────────────────
def generate_weekly_report() -> dict:
    """生成上周周报（每周一触发）"""
    today        = date.today()
    week_end     = datetime.combine(today, datetime.min.time())
    week_start   = datetime.combine(today - timedelta(days=7), datetime.min.time())
    sessions     = _query_sessions(week_start.timestamp(), week_end.timestamp())
    stats        = _build_stats(sessions)
    topics       = _extract_topics(sessions, 20)

    # 技能成长
    from skill_manager import list_skills
    skills = list_skills()
    week_start_str = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    upgraded_skills = [
        s for s in skills
        if s.get("last_improved","") >= week_start_str
    ]

    # 读取 Vault 用户档案（让 Anima 认识这个人）
    user_profile_snippet = ""
    try:
        from memory_injector import get_memory_injection
        vault_ctx = get_memory_injection("xi")
        if vault_ctx and len(vault_ctx) > 20:
            user_profile_snippet = vault_ctx[:400]
    except Exception:
        pass

    # 情感文字
    topic_text = "、".join(set(topics[:5])) if topics else "各种话题"
    profile_section = f"\n用户背景信息：\n{user_profile_snippet}\n" if user_profile_snippet else ""
    llm_prompt = f"""你是 Anima，用户最信任的 AI 伙伴。
今天是周一，请写一段上周周报的开场白（200字以内）。
{profile_section}
上周数据：
- 共 {stats['total_sessions']} 次对话
- 涉及主题：{topic_text}
- 共升级了 {len(upgraded_skills)} 个 Skill

风格要求：
1. 像一个一起度过了整整一周的伙伴
2. 如果知道用户背景，用具体细节让文字更有温度
3. 提到这一周的情绪变化或主要状态
4. 肯定用户这周做的事情
5. 对下一周表达一个期待
6. 温暖、有深度、不流于表面
7. 不要用「本周共产生X次对话」这种统计语言"""
    warm_text = _generate_warm_text_sync(llm_prompt) if sessions else \
        "这一周我们的对话不多，但没关系，新的一周从今天开始。"

    # 7日热力图数据
    heatmap = []
    for i in range(7):
        d   = (today - timedelta(days=7-i)).isoformat()
        heatmap.append({"date": d, "count": stats["by_day"].get(d, 0)})

    report = {
        "type":      "weekly",
        "date":      f"{(today - timedelta(days=7)).month}月{(today-timedelta(days=7)).day}日"
                     f" — {today.month}月{today.day}日",
        "date_iso":  today.isoformat(),
        "warm_text": warm_text,
        "stats":     stats,
        "chart_data": {
            "type":    "weekly",
            "heatmap": heatmap,
            "by_agent": [
                {"agent": k, "name": AGENT_DISPLAY.get(k,("🤖",k))[1],
                 "icon":  AGENT_DISPLAY.get(k,("🤖",k))[0], "count": v}
                for k, v in stats["by_agent"].items()
            ],
        },
        "topics":          topics[:8],
        "skill_upgrades":  [
            {"name": s.get("name",""), "version": s.get("version",1),
             "icon": s.get("icon","⚡"), "note": s.get("improvement_log",
             [{}])[-1].get("note","") if s.get("improvement_log") else ""}
            for s in upgraded_skills
        ],
        "generated_at": datetime.now().isoformat(),
    }

    out = REPORTS_DIR / f"weekly_{today.isoformat()}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    _mark_sent("weekly", today.isoformat())
    return report


def get_latest_report(report_type: str = "daily") -> Optional[dict]:
    """获取最新已生成的报告（无需重新生成）"""
    files = sorted(REPORTS_DIR.glob(f"{report_type}_*.json"), reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text("utf-8"))
    except Exception:
        return None


async def get_or_generate_report(report_type: str = "daily") -> dict:
    """获取或生成报告（前端启动时调用）"""
    if report_type == "daily":
        if should_send_daily():
            return await asyncio.to_thread(generate_daily_report)
        return get_latest_report("daily") or {"type":"daily","warm_text":"今天已经看过日报了。","stats":{}}
    else:
        if should_send_weekly():
            return await asyncio.to_thread(generate_weekly_report)
        return get_latest_report("weekly") or {"type":"weekly","warm_text":"本周报告已生成。","stats":{}}
