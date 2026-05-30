#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
routes/login.py — 本地密码登录 HTTP 端点

GET  /auth/status   → {"password_set": bool}
POST /auth/setup    → 首次设置密码（已设置则拒绝）  body: {password, confirm?, birth?}
POST /auth/login    → 校验密码                        body: {password}
POST /auth/reset    → 激活码离线重置密码              body: {code, password}
POST /auth/birth    → 保存/更新出生信息              body: {date,time,place,...}
GET  /auth/birth    → 读取出生信息

登录状态由前端在本会话内维持（本地离线应用，无服务端 session）。
"""
from aiohttp import web

import user_auth
from routes.auth import CORS_HEADERS, _json_error


def _ok(data: dict = None) -> web.Response:
    payload = {"ok": True}
    if data:
        payload.update(data)
    return web.json_response(payload, headers=CORS_HEADERS)


async def status_handler(request):
    return web.json_response(
        {"password_set": user_auth.is_password_set()},
        headers=CORS_HEADERS,
    )


async def setup_handler(request):
    if user_auth.is_password_set():
        return _json_error("密码已设置，请使用登录或重置", 409)
    try:
        body = await request.json()
    except Exception:
        return _json_error("请求体格式错误")
    password = (body.get("password") or "").strip()
    confirm = (body.get("confirm") or "").strip()
    if confirm and password != confirm:
        return _json_error("两次输入的密码不一致")
    try:
        user_auth.set_password(password)
    except ValueError as e:
        return _json_error(str(e))
    # 可选：同时保存出生信息
    birth = body.get("birth")
    if isinstance(birth, dict):
        try:
            user_auth.save_birth_info(birth)
        except Exception:
            pass
    return _ok()


async def login_handler(request):
    try:
        body = await request.json()
    except Exception:
        return _json_error("请求体格式错误")
    if not user_auth.is_password_set():
        return _json_error("尚未设置密码", 409)
    password = (body.get("password") or "").strip()
    if user_auth.verify_password(password):
        return _ok()
    return _json_error("密码错误", 401)


async def reset_handler(request):
    try:
        body = await request.json()
    except Exception:
        return _json_error("请求体格式错误")
    code = (body.get("code") or "").strip()
    password = (body.get("password") or "").strip()
    if not code:
        return _json_error("请输入激活码")
    try:
        ok = user_auth.reset_password_with_code(code, password)
    except ValueError as e:
        return _json_error(str(e))
    if ok:
        return _ok()
    return _json_error("激活码无效或已过期", 401)


async def birth_get_handler(request):
    return web.json_response(
        {"birth": user_auth.get_birth_info()},
        headers=CORS_HEADERS,
    )


async def birth_save_handler(request):
    try:
        body = await request.json()
    except Exception:
        return _json_error("请求体格式错误")
    try:
        user_auth.save_birth_info(body or {})
    except Exception as e:
        return _json_error(f"保存失败: {e}")
    return _ok({"birth": user_auth.get_birth_info()})


def register(app):
    app.router.add_get("/auth/status", status_handler)
    app.router.add_post("/auth/setup", setup_handler)
    app.router.add_post("/auth/login", login_handler)
    app.router.add_post("/auth/reset", reset_handler)
    app.router.add_get("/auth/birth", birth_get_handler)
    app.router.add_post("/auth/birth", birth_save_handler)
