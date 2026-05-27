"""
routes/core.py — 健康检查、用量统计、Agent 状态、历史会话
"""
from datetime import datetime
from aiohttp import web

from .auth import CORS_HEADERS, LOCAL_TOKEN, _is_local
from usage_tracker import UsageTracker
from config import LOG_DIR


async def health_handler(request):
    """GET /health — 健康检查（Tauri 前端用于判断后端是否就绪）"""
    payload: dict = {"status": "ok", "timestamp": datetime.now().isoformat()}
    if _is_local(request):
        payload["local_token"] = LOCAL_TOKEN
    return web.json_response(payload, headers=CORS_HEADERS)


async def usage_handler(request):
    """GET /usage?days=7"""
    days = int(request.query.get("days", 7))
    tracker = UsageTracker(LOG_DIR)
    data = tracker.get_daily_stats(days=days)
    return web.json_response(data, headers=CORS_HEADERS)


async def console_handler(request):
    """GET /console — 兼容旧版"""
    return web.json_response(
        {"deprecated": True, "message": "Use native overview panel"},
        headers=CORS_HEADERS,
    )


async def status_handler(request):
    """GET /status — 所有 agent 实时状态"""
    servers = request.app["servers"]
    result = {}
    for name, srv in servers.items():
        result[name] = {
            "agent":   srv.worker.name,
            "model":   srv.worker.model,
            "tools":   len(srv.worker.tool_defs),
            "busy":    srv.current_task is not None and not srv.current_task.done(),
            "session": srv.current_session_id,
        }
    return web.json_response(result, headers=CORS_HEADERS)


async def sessions_handler(request):
    """GET /sessions?agent=xi&limit=30 — 历史会话列表"""
    agent = request.query.get("agent") or None
    limit = min(int(request.query.get("limit", 30)), 100)
    search = request.app["search_engine"]
    sessions = search.list_sessions(agent=agent, limit=limit)
    return web.json_response({"sessions": sessions}, headers=CORS_HEADERS)


async def session_messages_handler(request):
    """GET /sessions/{session_id}/messages — 某会话的消息"""
    session_id = request.match_info["session_id"]
    search = request.app["search_engine"]
    messages = search.get_session_messages(session_id)
    return web.json_response({"messages": messages}, headers=CORS_HEADERS)


def register(app):
    app.router.add_get("/health",                         health_handler)
    app.router.add_get("/usage",                          usage_handler)
    app.router.add_get("/console",                        console_handler)
    app.router.add_get("/status",                         status_handler)
    app.router.add_get("/sessions",                       sessions_handler)
    app.router.add_get("/sessions/{session_id}/messages",  session_messages_handler)
