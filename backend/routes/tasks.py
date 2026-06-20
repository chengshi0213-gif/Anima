"""
routes/tasks.py — 异步任务 HTTP 接口

  GET  /tasks                       列出任务（?agent= 可选过滤）
  GET  /tasks/{task_id}             单个任务状态
  POST /tasks/{task_id}/cancel      取消任务
  POST /agent/{agent}/run_async     N3: 提交后台 Agent 会话（立即返回 task_id）

WS 端（ws_manager 的 task_submit/attach/list/cancel）是主路；HTTP 给非 WS 客户端
（脚本 / 通知中心 / 外部集成）一个旁路。
"""
import asyncio

from aiohttp import web

from .auth import CORS_HEADERS
from task_registry import get_registry


async def tasks_list(request):
    agent = request.query.get("agent")
    return web.json_response(
        {"tasks": get_registry().list(agent=agent)}, headers=CORS_HEADERS)


async def task_get(request):
    rec = get_registry().get_record(request.match_info["task_id"])
    if rec is None:
        return web.json_response({"error": "not found"}, status=404, headers=CORS_HEADERS)
    return web.json_response(rec, headers=CORS_HEADERS)


async def task_cancel(request):
    task_id = request.match_info["task_id"]
    ok = await get_registry().cancel(task_id)
    return web.json_response({"cancelled": ok, "task_id": task_id}, headers=CORS_HEADERS)


async def agent_run_async(request):
    """N3: 提交后台 Agent 任务（HTTP 版，无需 WS），立即返回 task_id。
    客户端可用 GET /tasks/{task_id} 轮询状态，或用 WS task_attach 接流。"""
    agent_name = request.match_info["agent"]
    servers = request.app.get("servers", {})
    server = servers.get(agent_name)
    if server is None:
        return web.json_response(
            {"error": f"未知 agent: {agent_name}"}, status=404, headers=CORS_HEADERS)
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "请求体需为 JSON {message, model?, session_id?}"},
            status=400, headers=CORS_HEADERS)
    message = body.get("message", "").strip()
    if not message:
        return web.json_response(
            {"error": "message 不能为空"}, status=400, headers=CORS_HEADERS)
    model = body.get("model")
    session_id = body.get("session_id", f"{agent_name}-async-{int(__import__('time').time())}")

    registry = get_registry()
    task = registry.create(agent_name, session_id, message)

    async def _run():
        registry.set_status(task, "running")
        try:
            result = await server.worker.run(
                message, session_id=session_id, model=model, ws=task)
            summary = result.get("summary", "")[:500]
            registry.set_status(task, "done", summary)
            task.result = result
            await task.send_json({"type": "response", "data": {
                "session_id": session_id, "task_id": task.task_id,
                **result,
            }})
        except asyncio.CancelledError:
            registry.set_status(task, "cancelled", "已取消")
            raise
        except Exception as e:
            registry.set_status(task, "error", str(e)[:500])
            await task.send_json({"type": "error", "message": str(e)[:200]})

    task.aio_task = asyncio.create_task(_run())
    return web.json_response(
        {"task_id": task.task_id, "session_id": session_id, "status": "queued"},
        headers=CORS_HEADERS)


def register(app):
    app.router.add_get("/tasks",                      tasks_list)
    app.router.add_get("/tasks/{task_id}",            task_get)
    app.router.add_post("/tasks/{task_id}/cancel",     task_cancel)
    app.router.add_post("/agent/{agent}/run_async",    agent_run_async)
