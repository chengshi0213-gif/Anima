"""
routes/data.py — Obsidian Vault + 记忆系统 + 项目管理 + 守藏 SOP
"""
import asyncio
import json
from aiohttp import web

from .auth import CORS_HEADERS, _json_error


# ══════════════════════════════════════════════════════
#  Obsidian Vault HTTP 接口
# ══════════════════════════════════════════════════════

async def vault_tree_handler(request):
    """GET /vault/tree — 返回 Vault 文件树"""
    from scholar_worker import get_vault_tree, get_vault_dir
    tree = await asyncio.to_thread(get_vault_tree)
    return web.json_response({"tree": tree, "vault_dir": get_vault_dir()}, headers=CORS_HEADERS)


async def vault_read_handler(request):
    """GET /vault/file?path=...  读取文件"""
    from scholar_worker import read_vault_file
    path = request.query.get("path","")
    if not path:
        return web.json_response({"error": "path required"}, status=400, headers=CORS_HEADERS)
    result = await asyncio.to_thread(read_vault_file, path)
    return web.json_response(result, headers=CORS_HEADERS)


async def vault_write_handler(request):
    """POST /vault/file  {path, content}"""
    from scholar_worker import write_vault_file
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    result = await asyncio.to_thread(write_vault_file, body.get("path",""), body.get("content",""))
    try:
        from memory_injector import invalidate_cache
        invalidate_cache()
    except Exception:
        pass
    return web.json_response(result, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  记忆系统统一接口（SQLite / Obsidian 双后端）
# ══════════════════════════════════════════════════════

async def memory_learn_handler(request):
    """POST /memory/learn — 「Anima 记住了」快捷写入"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)

    key        = (body.get("key")      or "").strip()
    value      = (body.get("value")    or "").strip()
    agent      = (body.get("agent")    or None)
    category   = (body.get("category") or "general").strip()
    importance = int(body.get("importance", 3))

    if not key or not value:
        return web.json_response({"error": "key/value required"}, status=400, headers=CORS_HEADERS)

    try:
        from memory_injector import write_memory
        eid = await asyncio.to_thread(write_memory, key, value, category, agent, importance)
        return web.json_response({
            "ok": True, "id": eid,
            "message": f"Anima 记住了：{key}",
        }, headers=CORS_HEADERS)
    except Exception as e:
        return _json_error(str(e), 500)


async def memory_backend_get(request):
    """GET /memory/backend — 获取当前后端类型及状态"""
    try:
        from memory_injector import get_backend
        status = await asyncio.to_thread(get_backend().get_status)
        return web.json_response(status, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


async def memory_backend_set(request):
    """POST /memory/backend — 切换后端"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)

    backend_type  = body.get("backend", "sqlite")
    obsidian_path = body.get("obsidian_path", "")
    migrate       = bool(body.get("migrate", False))

    from memory_injector import switch_backend
    result = await asyncio.to_thread(switch_backend, backend_type, obsidian_path, migrate)
    status = 200 if result.get("ok") else 400
    return web.json_response(result, status=status, headers=CORS_HEADERS)


async def memory_migrate_handler(request):
    """POST /memory/migrate — 迁移数据"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)

    to_type       = body.get("to", "sqlite")
    obsidian_path = body.get("obsidian_path", "")
    merge         = bool(body.get("merge", True))

    from memory_injector import migrate_data
    try:
        result = await asyncio.to_thread(migrate_data, to_type, obsidian_path, merge)
        return web.json_response(result, headers=CORS_HEADERS)
    except Exception as e:
        return _json_error(str(e), 500)


async def memory_list_handler(request):
    """GET /memory/entries?agent=&limit= — 列出记忆条目"""
    agent = request.rel_url.query.get("agent")
    limit = int(request.rel_url.query.get("limit", 100))
    from memory_injector import list_memory
    entries = await asyncio.to_thread(list_memory, agent)
    return web.json_response(
        [e.to_dict() for e in entries[:limit]],
        headers=CORS_HEADERS,
    )


async def memory_search_handler(request):
    """GET /memory/search?q=&agent= — 搜索记忆"""
    q     = request.rel_url.query.get("q", "")
    agent = request.rel_url.query.get("agent")
    if not q:
        return web.json_response([], headers=CORS_HEADERS)
    from memory_injector import search_memory
    results = await asyncio.to_thread(search_memory, q, agent)
    return web.json_response([e.to_dict() for e in results], headers=CORS_HEADERS)


async def memory_delete_handler(request):
    """DELETE /memory/entries/{id}"""
    entry_id = request.match_info.get("id", "")
    from memory_injector import delete_memory
    ok = await asyncio.to_thread(delete_memory, entry_id)
    if ok:
        return web.json_response({"ok": True}, headers=CORS_HEADERS)
    return web.json_response(
        {"ok": False, "message": "记忆未找到或当前后端不支持删除（Obsidian 模式请在 Obsidian 内手动删除）"},
        status=404, headers=CORS_HEADERS,
    )


# ══════════════════════════════════════════════════════
#  项目上下文管理
# ══════════════════════════════════════════════════════

async def projects_list_handler(request):
    """GET /projects — 列出所有项目"""
    try:
        from memory_injector import list_projects, get_active_project
        projects = await asyncio.to_thread(list_projects)
        active   = await asyncio.to_thread(get_active_project)
        return web.json_response({"projects": projects, "active": active}, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


async def project_create_handler(request):
    """POST /projects — 创建项目"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    name = (body.get("name") or "").strip()
    desc = (body.get("description") or "").strip()
    if not name:
        return web.json_response({"error": "name required"}, status=400, headers=CORS_HEADERS)
    try:
        from memory_injector import create_project
        result = await asyncio.to_thread(create_project, name, desc)
        return web.json_response(result, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


async def project_activate_handler(request):
    """POST /projects/{name}/activate — 设置活跃项目"""
    name = request.match_info.get("name", "")
    try:
        from memory_injector import set_active_project
        await asyncio.to_thread(set_active_project, name or None)
        return web.json_response({"ok": True, "active": name or None}, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


async def project_deactivate_handler(request):
    """POST /projects/deactivate — 清除活跃项目"""
    try:
        from memory_injector import set_active_project
        await asyncio.to_thread(set_active_project, None)
        return web.json_response({"ok": True, "active": None}, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  守藏 SOP
# ══════════════════════════════════════════════════════

async def shoucang_sop_handler(request):
    """POST /shoucang/sop — 触发守藏日常 SOP"""
    servers = request.app["servers"]
    shoucang_server = servers.get("shoucang")
    if not shoucang_server:
        return web.json_response({"error": "守藏 worker 未就绪"}, status=503, headers=CORS_HEADERS)

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    if body.get("stream"):
        # SSE 模式
        resp = web.StreamResponse(headers={
            **CORS_HEADERS,
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
        })
        await resp.prepare(request)

        async def push(step, total, msg):
            data = json.dumps({"step": step, "total": total, "msg": msg})
            try:
                await resp.write(f"data: {data}\n\n".encode())
            except Exception:
                pass

        loop = asyncio.get_event_loop()
        done_event = asyncio.Event()

        def sync_cb(step, total, msg):
            asyncio.run_coroutine_threadsafe(push(step, total, msg), loop)
            if step >= total and total > 0:
                loop.call_soon_threadsafe(done_event.set)

        async def _run_sop():
            try:
                await asyncio.to_thread(shoucang_server.worker.run_daily_sop, sync_cb)
            finally:
                done_event.set()

        asyncio.create_task(_run_sop())
        try:
            await asyncio.wait_for(done_event.wait(), timeout=600)
        except asyncio.TimeoutError:
            pass
        await push(0, 0, "SOP 执行完成")
        await resp.write_eof()
        return resp
    else:
        asyncio.create_task(asyncio.to_thread(shoucang_server.worker.run_daily_sop))
        return web.json_response({"ok": True, "message": "SOP 已在后台启动"}, headers=CORS_HEADERS)


def register(app):
    # Vault
    app.router.add_get("/vault/tree",                      vault_tree_handler)
    app.router.add_get("/vault/file",                      vault_read_handler)
    app.router.add_post("/vault/file",                     vault_write_handler)
    app.router.add_post("/shoucang/sop",                   shoucang_sop_handler)
    # Memory
    app.router.add_post("/memory/learn",                   memory_learn_handler)
    app.router.add_get("/memory/backend",                  memory_backend_get)
    app.router.add_post("/memory/backend",                 memory_backend_set)
    app.router.add_post("/memory/migrate",                 memory_migrate_handler)
    app.router.add_get("/memory/entries",                  memory_list_handler)
    app.router.add_get("/memory/search",                   memory_search_handler)
    app.router.add_delete("/memory/entries/{id}",          memory_delete_handler)
    # Projects — 注意：固定路径 deactivate 必须在参数路径 {name} 之前
    app.router.add_get("/projects",                        projects_list_handler)
    app.router.add_post("/projects",                       project_create_handler)
    app.router.add_post("/projects/deactivate",            project_deactivate_handler)
    app.router.add_post("/projects/{name}/activate",       project_activate_handler)
