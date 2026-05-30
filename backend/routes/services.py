"""
routes/services.py — Skills + 会员 + 报告 + Webhook + 推送通知
"""
import asyncio
from aiohttp import web

from .auth import CORS_HEADERS, _json_error
from skill_manager import (
    list_skills, get_skill, record_usage, upgrade_skill,
    install_community_skill, get_skills_summary,
    list_skill_references, load_skill_reference, bind_skill_to_agents,
)
from report_generator import (
    get_or_generate_report, get_latest_report,
    should_send_daily, should_send_weekly,
)
import notifier as _notifier


# ══════════════════════════════════════════════════════
#  Skill HTTP 接口
# ══════════════════════════════════════════════════════

async def skills_list_handler(request):
    """GET /skills — 列出所有 Skill（?category= 分类 ?agent= 只看某 agent 可用）"""
    category = request.query.get("category") or None
    agent = request.query.get("agent") or None
    skills = await asyncio.to_thread(list_skills, category, True, agent)
    summary = await asyncio.to_thread(get_skills_summary)
    return web.json_response({"skills": skills, "summary": summary}, headers=CORS_HEADERS)


async def skill_references_handler(request):
    """GET /skills/{skill_id}/references — 列出 bundle 的 reference 文件名"""
    sid = request.match_info["skill_id"]
    refs = await asyncio.to_thread(list_skill_references, sid)
    return web.json_response({"skill_id": sid, "references": refs}, headers=CORS_HEADERS)


async def skill_reference_get_handler(request):
    """GET /skills/{skill_id}/references/{ref} — 按需加载某 reference 内容
    ?agent= 用于校验 agent 绑定权限。"""
    sid = request.match_info["skill_id"]
    ref = request.match_info["ref"]
    agent = request.query.get("agent") or None
    content = await asyncio.to_thread(load_skill_reference, sid, ref, agent)
    if content is None:
        return web.json_response({"error": "reference 不存在或无权访问"},
                                 status=404, headers=CORS_HEADERS)
    return web.json_response({"skill_id": sid, "ref": ref, "content": content},
                             headers=CORS_HEADERS)


async def skill_bind_handler(request):
    """POST /skills/{skill_id}/bind — 设置 agent 绑定 {"agents": [...]}（空=全局）"""
    sid = request.match_info["skill_id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    agents = body.get("agents", [])
    if not isinstance(agents, list):
        return web.json_response({"error": "agents 必须是数组"}, status=400, headers=CORS_HEADERS)
    result = await asyncio.to_thread(bind_skill_to_agents, sid, agents)
    status = 404 if result.get("error") else 200
    return web.json_response(result, status=status, headers=CORS_HEADERS)


async def skill_get_handler(request):
    """GET /skills/{skill_id}"""
    sid = request.match_info["skill_id"]
    skill = await asyncio.to_thread(get_skill, sid)
    if not skill:
        return web.json_response({"error": "Skill 不存在"}, status=404, headers=CORS_HEADERS)
    return web.json_response(skill, headers=CORS_HEADERS)


async def skill_record_usage_handler(request):
    """POST /skills/{skill_id}/usage"""
    sid = request.match_info["skill_id"]
    try:
        body = await request.json()
        score = body.get("score")
    except Exception:
        score = None
    await asyncio.to_thread(record_usage, sid, score)
    return web.json_response({"ok": True}, headers=CORS_HEADERS)


async def skill_upgrade_handler(request):
    """POST /skills/{skill_id}/upgrade"""
    sid = request.match_info["skill_id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    result = await asyncio.to_thread(
        upgrade_skill, sid,
        body.get("new_prompt",""), body.get("note",""), body.get("weak_points")
    )
    return web.json_response(result, headers=CORS_HEADERS)


async def skill_install_handler(request):
    """POST /skills/install"""
    try:
        body = await request.json()
        url  = body.get("url","")
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    if not url:
        return web.json_response({"error": "url is required"}, status=400, headers=CORS_HEADERS)
    result = await asyncio.to_thread(install_community_skill, url)
    return web.json_response(result, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  会员系统 HTTP 接口
# ══════════════════════════════════════════════════════

async def membership_status_handler(request):
    """GET /membership/status"""
    from membership import get_membership
    return web.json_response(get_membership(), headers=CORS_HEADERS)


async def membership_activate_handler(request):
    """POST /membership/activate"""
    try:
        body = await request.json()
    except Exception:
        return _json_error("请求体格式错误")
    code = body.get("code", "").strip()
    if not code:
        return _json_error("请提供激活码")
    from membership import activate
    result = activate(code)
    status = 200 if result.get("ok") else 400
    return web.json_response(result, status=status, headers=CORS_HEADERS)


async def membership_deactivate_handler(request):
    """POST /membership/deactivate"""
    from membership import deactivate
    result = deactivate()
    return web.json_response(result, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  日报 / 周报 HTTP 接口
# ══════════════════════════════════════════════════════

async def report_status_handler(request):
    """GET /reports/status"""
    return web.json_response({
        "send_daily":  should_send_daily(),
        "send_weekly": should_send_weekly(),
    }, headers=CORS_HEADERS)


async def report_daily_handler(request):
    """GET /reports/daily"""
    force = request.query.get("force") == "1"
    if force:
        from report_generator import generate_daily_report
        report = await asyncio.to_thread(generate_daily_report)
    else:
        report = await get_or_generate_report("daily")
    return web.json_response(report or {}, headers=CORS_HEADERS)


async def report_weekly_handler(request):
    """GET /reports/weekly"""
    force = request.query.get("force") == "1"
    if force:
        from report_generator import generate_weekly_report
        report = await asyncio.to_thread(generate_weekly_report)
    else:
        report = await get_or_generate_report("weekly")
    return web.json_response(report or {}, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  Webhook 触发
# ══════════════════════════════════════════════════════

async def webhook_trigger_handler(request):
    """POST /hook/{agent_id} — 外部 Webhook 触发 Agent 任务"""
    agent_id = request.match_info.get("agent_id", "xi")
    servers  = request.app["servers"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return web.json_response({"error": "prompt required"}, status=400, headers=CORS_HEADERS)

    try:
        import config as _cfg
        wh_token = getattr(_cfg, "WEBHOOK_TOKEN", None) or ""
        if wh_token and body.get("token") != wh_token:
            return web.json_response({"error": "invalid token"}, status=403, headers=CORS_HEADERS)
    except Exception:
        pass

    srv = servers.get(agent_id)
    if not srv:
        return web.json_response({"error": f"unknown agent: {agent_id}"}, status=404, headers=CORS_HEADERS)

    context = (body.get("context") or "").strip()
    full_prompt = f"{prompt}\n\n附加上下文：\n{context}" if context else prompt

    return_result = body.get("return_result", False)
    task_id = f"hook_{agent_id}_{int(__import__('time').time())}"

    if return_result:
        try:
            result = await asyncio.wait_for(srv.worker.run(full_prompt), timeout=120)
            return web.json_response({
                "ok": True, "task_id": task_id,
                "result": result.get("summary", result.get("output", "")),
            }, headers=CORS_HEADERS)
        except asyncio.TimeoutError:
            return web.json_response({"error": "timeout (120s)"}, status=504, headers=CORS_HEADERS)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)
    else:
        asyncio.create_task(srv.worker.run(full_prompt))
        return web.json_response(
            {"ok": True, "task_id": task_id, "message": f"Agent {agent_id} 已在后台启动"},
            status=202, headers=CORS_HEADERS,
        )


# ══════════════════════════════════════════════════════
#  推送通知渠道
# ══════════════════════════════════════════════════════

async def notif_list_handler(request):
    return web.json_response({"channels": _notifier.list_channels()}, headers=CORS_HEADERS)

async def notif_add_handler(request):
    try:
        b = await request.json()
    except Exception:
        return web.json_response({"error":"invalid json"}, status=400, headers=CORS_HEADERS)
    ch = _notifier.add_channel(b.get("name",""), b.get("type","feishu"), b.get("webhook",""), b.get("secret",""))
    return web.json_response(ch, headers=CORS_HEADERS)

async def notif_delete_handler(request):
    ok = _notifier.delete_channel(request.match_info["ch_id"])
    return web.json_response({"deleted": ok}, headers=CORS_HEADERS)

async def notif_test_handler(request):
    ok = await asyncio.to_thread(_notifier.test_channel, request.match_info["ch_id"])
    return web.json_response({"ok": ok}, headers=CORS_HEADERS)

async def notif_push_handler(request):
    try:
        b = await request.json()
    except Exception:
        return web.json_response({"error":"invalid json"}, status=400, headers=CORS_HEADERS)
    results = await asyncio.to_thread(_notifier.push, b.get("title","通知"), b.get("content",""))
    return web.json_response({"results": results}, headers=CORS_HEADERS)


def register(app):
    # Skills
    app.router.add_get("/skills",                          skills_list_handler)
    app.router.add_post("/skills/install",                 skill_install_handler)
    app.router.add_get("/skills/{skill_id}",               skill_get_handler)
    app.router.add_get("/skills/{skill_id}/references",    skill_references_handler)
    app.router.add_get("/skills/{skill_id}/references/{ref}", skill_reference_get_handler)
    app.router.add_post("/skills/{skill_id}/usage",        skill_record_usage_handler)
    app.router.add_post("/skills/{skill_id}/upgrade",      skill_upgrade_handler)
    app.router.add_post("/skills/{skill_id}/bind",         skill_bind_handler)
    # Membership
    app.router.add_get("/membership/status",               membership_status_handler)
    app.router.add_post("/membership/activate",            membership_activate_handler)
    app.router.add_post("/membership/deactivate",          membership_deactivate_handler)
    # Reports
    app.router.add_get("/reports/status",                  report_status_handler)
    app.router.add_get("/reports/daily",                   report_daily_handler)
    app.router.add_get("/reports/weekly",                  report_weekly_handler)
    # Webhook
    app.router.add_post("/hook/{agent_id}",                webhook_trigger_handler)
    # Notifier
    app.router.add_get("/notifier/channels",              notif_list_handler)
    app.router.add_post("/notifier/channels",             notif_add_handler)
    app.router.add_delete("/notifier/channels/{ch_id}",   notif_delete_handler)
    app.router.add_post("/notifier/channels/{ch_id}/test",notif_test_handler)
    app.router.add_post("/notifier/push",                 notif_push_handler)
