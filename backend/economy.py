#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
economy.py — 成就 + 灵犀经济（养成，不赌场）

设计原则：
  - 成就由**真实使用信号**计算（对话数 / 活跃天数 / 工作流数 / 技能段位…），
    不是随机抽卡。signals 由上层（路由）从现有 manager 汇总后注入，本模块纯逻辑、可单测。
  - **灵犀**是"心力/羁绊"的具象，不是钱：达成成就后**领取**得灵犀；灵犀**兑换**解锁
    社区技能 / 人格世界皮肤等"锦上添花"，**绝不锁核心功能**。
  - 状态持久化在 ~/.anima/data/economy.json。

对外：
  status(signals) · claim(achievement_id, signals) · spend(amount, item) · balance()
"""
from __future__ import annotations

import json
from datetime import date

try:
    from config import DATA_DIR
    _PATH = DATA_DIR / "economy.json"
except Exception:  # 单测可不依赖 config
    import pathlib
    _PATH = pathlib.Path.home() / ".anima" / "data" / "economy.json"

# 段位（复用前端 lvl 视觉）：fan/bronze/silver/gold/diamond/legend
ACHIEVEMENTS: list[dict] = [
    # —— 里程碑 ——
    {"id": "first_words", "name": "初次相遇", "icon": "🌱", "tier": "bronze", "cat": "里程碑",
     "desc": "和 Anima 说出第一句话", "sig": "messages", "need": 1, "reward": 20},
    {"id": "hundred",     "name": "百句之约", "icon": "💬", "tier": "silver", "cat": "里程碑",
     "desc": "累计 100 条对话", "sig": "messages", "need": 100, "reward": 60},
    {"id": "thousand",    "name": "千言相伴", "icon": "🗨️", "tier": "diamond", "cat": "里程碑",
     "desc": "累计 1000 条对话", "sig": "messages", "need": 1000, "reward": 200},
    # —— 探索 ——
    {"id": "first_flow",  "name": "初构工作流", "icon": "⚡", "tier": "silver", "cat": "创造",
     "desc": "搭建并保存第一条工作流", "sig": "workflows", "need": 1, "reward": 60},
    {"id": "first_divine","name": "一窥天机", "icon": "🔮", "tier": "silver", "cat": "探索",
     "desc": "让 Anima 为你排一次命盘", "sig": "divinations", "need": 1, "reward": 50},
    # —— 成长 ——
    {"id": "skill_grow",  "name": "技能精进", "icon": "📜", "tier": "gold", "cat": "成长",
     "desc": "精进技能 5 次", "sig": "skills_upgraded", "need": 5, "reward": 80},
    {"id": "collector",   "name": "博采众长", "icon": "🧩", "tier": "gold", "cat": "成长",
     "desc": "技能库达到 50 个", "sig": "skills_total", "need": 50, "reward": 70},
    {"id": "skill_legend","name": "技近乎道", "icon": "⚔️", "tier": "legend", "cat": "成长",
     "desc": "拥有一个「传说」段位技能", "sig": "legend_skills", "need": 1, "reward": 160},
    # —— 陪伴 ——
    {"id": "memory_keeper","name": "守先待后", "icon": "🏛️", "tier": "gold", "cat": "陪伴",
     "desc": "存下 20 条记忆", "sig": "memories", "need": 20, "reward": 70},
    {"id": "week_companion","name": "朝夕相处", "icon": "🌙", "tier": "diamond", "cat": "陪伴",
     "desc": "陪伴你 7 天", "sig": "active_days", "need": 7, "reward": 120},
]
_BY_ID = {a["id"]: a for a in ACHIEVEMENTS}


def _load() -> dict:
    if _PATH.exists():
        try:
            return json.loads(_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"lingxi": 0, "claimed": {}, "seen": {}, "unlocks": [], "grants": {}}


def _save(st: dict) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _eval(a: dict, signals: dict):
    cur = int(signals.get(a["sig"], 0) or 0)
    need = a["need"]
    return (cur >= need, min(cur, need), need)


def status(signals: dict) -> dict:
    """汇总：余额 + 全部成就（达成/进度/已领取）。顺带记录首次达成时间。"""
    st = _load()
    today = date.today().isoformat()
    changed = False
    out = []
    total_unclaimed = 0
    for a in ACHIEVEMENTS:
        done, cur, need = _eval(a, signals)
        if done and a["id"] not in st["seen"]:
            st["seen"][a["id"]] = today; changed = True
        claimed = a["id"] in st["claimed"]
        if done and not claimed:
            total_unclaimed += a["reward"]
        out.append({**a, "done": done, "cur": cur, "claimed": claimed,
                    "progress": round(cur / need * 100) if need else 100})
    if changed:
        _save(st)
    done_n = sum(1 for o in out if o["done"])
    return {"lingxi": st["lingxi"], "achievements": out, "unlocks": st["unlocks"],
            "summary": {"total": len(ACHIEVEMENTS), "done": done_n,
                        "claimable": total_unclaimed}}


def claim(achievement_id: str, signals: dict) -> dict:
    """领取一个已达成成就的灵犀奖励。"""
    a = _BY_ID.get(achievement_id)
    if not a:
        return {"ok": False, "error": "未知成就"}
    done, _, _ = _eval(a, signals)
    if not done:
        return {"ok": False, "error": "尚未达成"}
    st = _load()
    if achievement_id in st["claimed"]:
        return {"ok": False, "error": "已领取", "lingxi": st["lingxi"]}
    st["claimed"][achievement_id] = date.today().isoformat()
    st["lingxi"] = int(st["lingxi"]) + int(a["reward"])
    _save(st)
    return {"ok": True, "reward": a["reward"], "lingxi": st["lingxi"]}


def spend(amount: int, item: str) -> dict:
    """花灵犀兑换解锁（社区技能 / 世界皮肤等）。"""
    amount = int(amount)
    st = _load()
    if amount <= 0:
        return {"ok": False, "error": "金额无效"}
    if st["lingxi"] < amount:
        return {"ok": False, "error": "灵犀不足", "lingxi": st["lingxi"]}
    if item in st["unlocks"]:
        return {"ok": False, "error": "已解锁", "lingxi": st["lingxi"]}
    st["lingxi"] -= amount
    st["unlocks"].append(item)
    _save(st)
    return {"ok": True, "lingxi": st["lingxi"], "unlocks": st["unlocks"]}


def grant(amount: int, key: str, reason: str = "") -> dict:
    """幂等发放灵犀（非成就来源，如邀请奖励）。同一 key 只发一次。
    返回 {"ok", "granted", "lingxi", "reason"}。容错、绝不抛。"""
    try:
        amount = int(amount)
        if amount <= 0 or not key:
            return {"ok": False, "reason": "invalid", "lingxi": balance()}
        st = _load()
        grants = st.setdefault("grants", {})
        if key in grants:
            return {"ok": False, "reason": "already_granted", "lingxi": int(st["lingxi"])}
        st["lingxi"] = int(st["lingxi"]) + amount
        grants[key] = {"amount": amount, "reason": reason, "date": date.today().isoformat()}
        _save(st)
        return {"ok": True, "granted": amount, "lingxi": st["lingxi"], "reason": reason}
    except Exception:
        return {"ok": False, "reason": "error", "lingxi": balance()}


def grants() -> dict:
    """返回已发放的额外灵犀记录（key -> {amount,reason,date}）。"""
    try:
        return dict(_load().get("grants", {}))
    except Exception:
        return {}


def balance() -> int:
    return int(_load()["lingxi"])


def bump(name: str, n: int = 1) -> int:
    """累加一个使用计数器（如 divinations 排盘次数）。返回新值。容错、绝不抛。"""
    try:
        st = _load()
        c = st.setdefault("counters", {})
        c[name] = int(c.get(name, 0)) + int(n)
        _save(st)
        return c[name]
    except Exception:
        return 0


def counters() -> dict:
    try:
        return dict(_load().get("counters", {}))
    except Exception:
        return {}
