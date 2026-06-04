#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""routes/economy.py — 成就 + 灵犀经济 HTTP 接口。信号从现有 manager 汇总（真实使用驱动）。"""
from __future__ import annotations
import json

from aiohttp import web

import economy as _ec
try:
    import skill_manager as _sk
except Exception:
    _sk = None

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def _legend_count(skills) -> int:
    """与前端同公式：品质 Q + 历练 M ≥ 165 即「传说」。"""
    n = 0
    for s in skills or []:
        try:
            score = float(s.get("avg_score") or 0)
            ver = int(s.get("version") or 1)
            usage = int(s.get("usage_count") or 0)
            upg = len(s.get("improvement_log") or []) or max(0, ver - 1)
            srcbase = 26 if s.get("premium") else (18 if s.get("source") == "community" else 24)
            Q = (srcbase + score * 8
                 + min(len(s.get("use_cases") or []), 5) * 2.5
                 + min(len(s.get("tags") or []), 5) * 1.5
                 + (4 if len(s.get("description") or "") > 40 else 0)
                 + min(max(0, ver - 1), 5) * 2)
            M = usage * 1.5 + upg * 12
            if Q + M >= 165:
                n += 1
        except Exception:
            continue
    return n


def _gather_signals(app) -> dict:
    sig = {}
    if _sk is not None:
        try:
            skills = _sk.list_skills(enabled_only=False)
            summ = _sk.get_skills_summary()
            sig["skills_total"] = int(summ.get("total") or len(skills))
            sig["skills_upgraded"] = int(summ.get("upgraded") or 0)
            sig["legend_skills"] = _legend_count(skills)
        except Exception:
            pass
    try:
        sig["workflows"] = len(app["workflow_mgr"].list_all())
    except Exception:
        pass
    # 对话数 / 人格 / 活跃天数：从真实使用日志汇总（best-effort）
    try:
        ut = app.get("usage_tracker")
        if ut is not None:
            ss = ut.get_signal_stats(3650)
            per = ss.get("per_agent", {})
            sig["messages"] = int(ss.get("messages", 0))
            sig["personas_used"] = sum(1 for a in ("xi", "yiyi", "tianyuan", "shoucang")
                                       if int(per.get(a, 0)) > 0)
            sig["active_days"] = int(ss.get("active_days", 0))
    except Exception:
        pass
    # 守藏记忆条数
    try:
        from memory_injector import get_backend
        sig["memories"] = int(get_backend().get_status().get("entries", 0) or 0)
    except Exception:
        pass
    # 累计计数器（排盘次数等）
    try:
        for k, v in _ec.counters().items():
            sig.setdefault(k, int(v))
    except Exception:
        pass
    return sig


async def status_handler(request):
    sig = _gather_signals(request.app)
    return web.json_response(_ec.status(sig), headers=CORS_HEADERS)


async def claim_handler(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    aid = body.get("id") or request.match_info.get("id", "")
    sig = _gather_signals(request.app)
    return web.json_response(_ec.claim(aid, sig), headers=CORS_HEADERS)


async def spend_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid json"}, status=400, headers=CORS_HEADERS)
    return web.json_response(_ec.spend(body.get("amount", 0), body.get("item", "")), headers=CORS_HEADERS)


def register(app):
    app.router.add_get("/economy/status", status_handler)
    app.router.add_post("/economy/claim", claim_handler)
    app.router.add_post("/economy/spend", spend_handler)
