"""
routes/tasks.py — M12 内核2：异步任务的 HTTP 只读 + 取消接口。

  GET  /tasks                 列出任务（?agent= 可选过滤）
  GET  /tasks/{task_id}       单个任务状态
  POST /tasks/{task_id}/cancel 取消任务

WS 端（ws_manager 的 task_submit/attach/list/cancel）是主路；这里给非 WS 客户端
（脚本 / 通知中心 / 外部集成）一个只读 + 取消的旁路。
"""
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


def register(app):
    app.router.add_get("/tasks",                  tasks_list)
    app.router.add_get("/tasks/{task_id}",        task_get)
    app.router.add_post("/tasks/{task_id}/cancel", task_cancel)
