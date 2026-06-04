#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""routes/invite.py — 邀请码 HTTP 接口。"""
from __future__ import annotations

import asyncio
from aiohttp import web
from .auth import CORS_HEADERS
import invite as _inv
try:
    import invite_mailer as _mailer
except Exception:
    _mailer = None


# GET /invite/check?device_id=xxx
async def check_handler(request):
    """检查该设备是否已激活（前端 onboarding 用）。"""
    did = request.query.get("device_id", "").strip() or _inv.get_device_id()
    activated = await _inv.check_activated(did)
    return web.json_response({"activated": activated}, headers=CORS_HEADERS)


# POST /invite/verify  {"code": "XXXX-YYYY"}
async def verify_handler(request):
    """预验证码（输入框失焦时即时反馈，不消耗码）。"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "reason": "invalid_json"}, status=400, headers=CORS_HEADERS)
    code = (body.get("code") or "").strip()
    if not code:
        return web.json_response({"ok": False, "reason": "empty_code"}, status=400, headers=CORS_HEADERS)
    result = await _inv.verify_code(code)
    return web.json_response(result, headers=CORS_HEADERS)


# POST /invite/activate  {"code": "XXXX-YYYY", "device_id": "..."}
async def activate_handler(request):
    """激活邀请码 — 每台设备只能激活一次。"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "reason": "invalid_json"}, status=400, headers=CORS_HEADERS)
    code = (body.get("code") or "").strip()
    did  = (body.get("device_id") or "").strip() or _inv.get_device_id()
    if not code:
        return web.json_response({"ok": False, "reason": "empty_code"}, status=400, headers=CORS_HEADERS)
    result = await _inv.activate_code(code, did)
    status = 200 if result.get("ok") else 400
    return web.json_response(result, status=status, headers=CORS_HEADERS)


# GET /invite/my?device_id=xxx
async def my_codes_handler(request):
    """列出当前用户的邀请码 + 配额信息。"""
    did = request.query.get("device_id", "").strip() or _inv.get_device_id()
    result = await _inv.get_user_codes(did)
    return web.json_response(result, headers=CORS_HEADERS)


# POST /invite/generate  {"device_id": "...", "n": 1}
async def generate_handler(request):
    """生成邀请码（受配额限制）。"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "reason": "invalid_json"}, status=400, headers=CORS_HEADERS)
    did = (body.get("device_id") or "").strip() or _inv.get_device_id()
    n   = min(int(body.get("n", 1)), 3)
    result = await _inv.generate_codes(did, n)
    status = 200 if result.get("ok") else 400
    return web.json_response(result, status=status, headers=CORS_HEADERS)


# POST /invite/reconcile — 邀请人对账，补发未领的邀请奖励灵犀
async def reconcile_handler(request):
    did = request.query.get("device_id", "").strip() or None
    try:
        body = await request.json()
        did = (body.get("device_id") or "").strip() or did
    except Exception:
        pass
    result = await _inv.reconcile_invite_rewards(did)
    return web.json_response(result, headers=CORS_HEADERS)


# ── 邮箱管家（仅总代理实例）─────────────────────────────────
async def mailer_get_handler(request):
    if _mailer is None:
        return web.json_response({"available": False}, headers=CORS_HEADERS)
    cfg = await asyncio.to_thread(_mailer.config_public)
    status = _mailer.mailer.status()
    return web.json_response({"available": True, "config": cfg, "status": status}, headers=CORS_HEADERS)


async def mailer_save_handler(request):
    if _mailer is None:
        return web.json_response({"ok": False, "error": "unavailable"}, status=400, headers=CORS_HEADERS)
    try:
        b = await request.json()
    except Exception:
        b = {}
    cfg = await asyncio.to_thread(_mailer.save_config, b)
    # 按 enabled 启停
    if cfg.get("enabled"):
        res = _mailer.mailer.start()
    else:
        res = _mailer.mailer.stop()
    return web.json_response({"ok": True, "config": _mailer.config_public(),
                              "apply": res, "status": _mailer.mailer.status()}, headers=CORS_HEADERS)


async def mailer_test_handler(request):
    if _mailer is None:
        return web.json_response({"ok": False, "error": "unavailable"}, status=400, headers=CORS_HEADERS)
    try:
        b = await request.json()
    except Exception:
        b = {}
    # 测试用：合并已存配置（密码掩码时用已存的）
    stored = await asyncio.to_thread(_mailer.load_config)
    for k in ("imap_host", "imap_port", "smtp_host", "smtp_port", "email"):
        if b.get(k) in (None, ""):
            b[k] = stored.get(k)
    if b.get("password") in (None, "", "********"):
        b["password"] = stored.get("password")
    res = await asyncio.to_thread(_mailer.test_connection, b)
    return web.json_response(res, headers=CORS_HEADERS)


async def mailer_poll_handler(request):
    if _mailer is None:
        return web.json_response({"ok": False, "error": "unavailable"}, status=400, headers=CORS_HEADERS)
    res = await _mailer.mailer.poll_now()
    return web.json_response({"ok": True, **res}, headers=CORS_HEADERS)


# GET /invite/stats  （仅本地/管理员调用）
async def stats_handler(request):
    result = await _inv.stats()
    return web.json_response(result, headers=CORS_HEADERS)


def register(app):
    app.router.add_get ("/invite/check",     check_handler)
    app.router.add_post("/invite/verify",    verify_handler)
    app.router.add_post("/invite/activate",  activate_handler)
    app.router.add_get ("/invite/my",        my_codes_handler)
    app.router.add_post("/invite/generate",  generate_handler)
    app.router.add_post("/invite/reconcile", reconcile_handler)
    app.router.add_get ("/invite/stats",     stats_handler)
    # 邮箱管家
    app.router.add_get ("/invite/mailer",      mailer_get_handler)
    app.router.add_post("/invite/mailer",      mailer_save_handler)
    app.router.add_post("/invite/mailer/test", mailer_test_handler)
    app.router.add_post("/invite/mailer/poll", mailer_poll_handler)
