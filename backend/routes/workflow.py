"""
routes/workflow.py — 工作流 CRUD + 定时任务 + 文件监视器 + 群聊 + 执行引擎
"""
import asyncio
import json
import time as _time
import aiohttp
from aiohttp import web

from .auth import CORS_HEADERS
from knowledge_base import kb as _kb
from scheduler import scheduler as _scheduler
from file_watcher import watcher as _watcher
from workflow_ai import ai_build_workflow
from workflow_engine import run_workflow, run_workflow_graph, WorkflowRunner


# ══════════════════════════════════════════════════════
#  工作流 CRUD
# ══════════════════════════════════════════════════════

async def workflow_list_handler(request):
    """GET /workflow/list — 列出已保存工作流"""
    wm = request.app["workflow_mgr"]
    items = wm.list_all()
    return web.json_response({"workflows": items}, headers=CORS_HEADERS)


async def workflow_save_handler(request):
    """POST /workflow/save — 保存工作流定义"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    wm = request.app["workflow_mgr"]
    result = wm.save_workflow(body.get("id"), body.get("name","未命名"), body.get("steps",[]))
    return web.json_response(result, headers=CORS_HEADERS)


async def workflow_ai_build_handler(request):
    """POST /workflow/ai_build — 把一句话目标编译成可编辑的工作流图。

    body: {description, current_steps?}
      - description: 用户的目标 / 修改指令（必填）。
      - current_steps: 传了就是"在现有图上改"（对话式编辑）。
    返回 workflow_ai.ai_build_workflow 的结构：
      {ok, name, steps, explanation, variables, warnings} 或 {ok:False, error}。

    用陶朱（tianyuan）的模型当规划器——它本就是"把模糊目标拆成计划"的人格；
    拿不到就退回 xi。注意走 _call_api(tools=None) 纯生成，不触发 ReAct/delegate。
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    description   = (body.get("description") or "").strip()
    current_steps = body.get("current_steps") or None
    if not description:
        return web.json_response({"ok": False, "error": "目标描述为空"},
                                 status=400, headers=CORS_HEADERS)

    servers = request.app["servers"]
    srv = servers.get("tianyuan") or servers.get("xi")
    if srv is None:
        return web.json_response({"ok": False, "error": "无可用规划器 agent"},
                                 status=503, headers=CORS_HEADERS)

    result = await ai_build_workflow(srv.worker, description, current_steps)
    status = 200 if result.get("ok") else 422
    return web.json_response(result, status=status, headers=CORS_HEADERS)


async def workflow_delete_handler(request):
    """DELETE /workflow/{wf_id}"""
    wf_id = request.match_info["wf_id"]
    wm = request.app["workflow_mgr"]
    ok = wm.delete_workflow(wf_id)
    return web.json_response({"deleted": ok}, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  工作流执行引擎（逻辑已抽到 workflow_engine.WorkflowRunner）
# ══════════════════════════════════════════════════════

def _planner_for(servers):
    """挑一个规划器（供 AI 路由 / 陶朱动态展开），拿不到返回 None。"""
    gen = servers.get("tianyuan") or servers.get("xi")
    return gen.worker if gen else None


async def workflow_run_handler(request):
    """POST /workflow/run — 一次性（阻塞）执行工作流，最后返回全部结果。

    支持节点类型: sequential / parallel / condition / router / loop / human / taozu。
    人审节点在阻塞模式下默认放行（无交互通道）；要交互人审/实时回显请走
    WebSocket /ws/workflow。
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)

    steps   = body.get("steps", [])
    use_kb  = body.get("use_kb", False)
    servers = request.app["servers"]
    if not steps:
        return web.json_response({"error": "steps 为空"}, status=400, headers=CORS_HEADERS)

    result = await run_workflow(steps, servers, use_kb=use_kb, kb=_kb,
                                generator=_planner_for(servers))
    return web.json_response({
        "results":     result["results"],
        "ok":          result["ok"],
        "stopped":     result.get("stopped", False),
        "stop_reason": result.get("stop_reason", ""),
        "error":       result.get("error"),
    }, headers=CORS_HEADERS)


async def _safe_ws_send(ws, payload):
    try:
        await ws.send_json(payload)
    except Exception:
        pass


async def workflow_ws_handler(request):
    """WS /ws/workflow — 流式执行 + 交互式人审。

    客户端 → 服务端:
      {"action":"run","steps":[...],"use_kb":false}
      {"action":"gate_response","decision":"approve|reject","note":"..."}
      {"action":"cancel"}
    服务端 → 客户端（engine emit 的事件）:
      {"event":"start|step_start|step_retry|step_done|human_gate|
                router_decision|taozu_expanded|done|error", ...}
    """
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    servers = request.app["servers"]

    pending_gate = {"fut": None}
    run_task = {"t": None}

    async def emit(ev):
        await _safe_ws_send(ws, ev)

    async def gate(step_idx, message):
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        pending_gate["fut"] = fut
        try:
            return await fut
        finally:
            pending_gate["fut"] = None

    try:
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                await _safe_ws_send(ws, {"event": "error", "message": "无效 JSON"})
                continue
            action = data.get("action", "")

            if action == "run":
                if run_task["t"] and not run_task["t"].done():
                    await _safe_ws_send(ws, {"event": "error", "message": "已有工作流在运行"})
                    continue
                graph  = data.get("graph")
                steps  = data.get("steps", [])
                use_kb = data.get("use_kb", False)
                if not graph and not steps:
                    await _safe_ws_send(ws, {"event": "error", "message": "graph / steps 均为空"})
                    continue

                async def _go(graph=graph, steps=steps, use_kb=use_kb):
                    kw = dict(use_kb=use_kb, kb=_kb, generator=_planner_for(servers),
                              emit=emit, gate=gate)
                    try:
                        if graph:
                            await run_workflow_graph(graph, servers, **kw)   # n8n/扣子 DAG
                        else:
                            await run_workflow(steps, servers, **kw)         # 线性步骤
                    except asyncio.CancelledError:
                        await _safe_ws_send(ws, {"event": "error", "message": "已取消"})
                    except Exception as e:  # noqa: BLE001
                        await _safe_ws_send(ws, {"event": "error", "message": str(e)})
                run_task["t"] = asyncio.create_task(_go())

            elif action == "gate_response":
                fut = pending_gate["fut"]
                if fut and not fut.done():
                    fut.set_result({"action": data.get("decision", "approve"),
                                    "note": data.get("note", "")})

            elif action == "cancel":
                if run_task["t"] and not run_task["t"].done():
                    run_task["t"].cancel()
                # 解开正卡在人审上的执行，避免悬挂
                fut = pending_gate["fut"]
                if fut and not fut.done():
                    fut.set_result({"action": "reject", "note": "已取消"})
    finally:
        if run_task["t"] and not run_task["t"].done():
            run_task["t"].cancel()
    return ws


# ══════════════════════════════════════════════════════
#  定时任务
# ══════════════════════════════════════════════════════

async def sched_list_handler(request):
    """GET /scheduler/tasks"""
    return web.json_response({"tasks": _scheduler.list_tasks()}, headers=CORS_HEADERS)

async def sched_logs_handler(request):
    """GET /scheduler/logs?task_id=&limit=50"""
    task_id = request.query.get("task_id") or None
    limit   = int(request.query.get("limit", 50))
    return web.json_response({"logs": _scheduler.list_logs(task_id, limit)}, headers=CORS_HEADERS)

async def sched_add_handler(request):
    """POST /scheduler/tasks"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    try:
        task = _scheduler.add_task(
            name          = body.get("name", "定时任务"),
            agent         = body.get("agent", "xi"),
            prompt        = body.get("prompt", ""),
            trigger_type  = body.get("trigger_type", "interval"),
            trigger_value = body.get("trigger_value", "1h"),
        )
        return web.json_response(task, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

async def sched_toggle_handler(request):
    """POST /scheduler/tasks/{task_id}/toggle"""
    task_id = request.match_info["task_id"]
    result  = _scheduler.toggle_task(task_id)
    return web.json_response(result, headers=CORS_HEADERS)

async def sched_delete_handler(request):
    """DELETE /scheduler/tasks/{task_id}"""
    task_id = request.match_info["task_id"]
    ok = _scheduler.delete_task(task_id)
    return web.json_response({"deleted": ok}, headers=CORS_HEADERS)

async def sched_run_now_handler(request):
    """POST /scheduler/tasks/{task_id}/run — 立即执行一次"""
    task_id = request.match_info["task_id"]
    task = _scheduler._tasks.get(task_id)
    if not task:
        return web.json_response({"error": "任务不存在"}, status=404, headers=CORS_HEADERS)
    asyncio.create_task(_scheduler._execute_task(task_id))
    return web.json_response({"queued": True}, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  文件监视器
# ══════════════════════════════════════════════════════

async def fw_list_handler(request):
    return web.json_response({"rules": _watcher.list_rules()}, headers=CORS_HEADERS)

async def fw_events_handler(request):
    rule_id = request.query.get("rule_id") or None
    limit   = int(request.query.get("limit", 50))
    return web.json_response({"events": _watcher.list_events(rule_id, limit)}, headers=CORS_HEADERS)

async def fw_add_handler(request):
    try:
        b = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    try:
        rule = _watcher.add_rule(
            name=b.get("name","监视器"),
            watch_path=b.get("watch_path",""),
            pattern=b.get("pattern","*"),
            events=b.get("events",["created","modified"]),
            agent=b.get("agent","xi"),
            prompt_template=b.get("prompt_template","文件 {filename} 发生了 {event} 事件，请分析或处理。"),
        )
        return web.json_response(rule, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

async def fw_toggle_handler(request):
    rule_id = request.match_info["rule_id"]
    result  = _watcher.toggle_rule(rule_id)
    return web.json_response(result, headers=CORS_HEADERS)

async def fw_delete_handler(request):
    rule_id = request.match_info["rule_id"]
    ok = _watcher.delete_rule(rule_id)
    return web.json_response({"deleted": ok}, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  多 Agent 群聊
# ══════════════════════════════════════════════════════

async def groupchat_run_handler(request):
    """POST /groupchat/run
    Body: {"topic":"...", "agents":["xi","shoucang",...], "rounds":2}
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error":"invalid json"}, status=400, headers=CORS_HEADERS)

    topic   = body.get("topic", "").strip()
    agents  = body.get("agents", [])
    rounds  = max(1, min(int(body.get("rounds", 1)), 3))
    servers = request.app["servers"]

    if not topic:
        return web.json_response({"error":"topic 为空"}, status=400, headers=CORS_HEADERS)
    if not agents:
        return web.json_response({"error":"agents 为空"}, status=400, headers=CORS_HEADERS)

    from .config import DEFAULT_AGENT_NAMES, _load_agent_config

    history   = []
    messages  = []

    for rnd in range(rounds):
        for agent_id in agents:
            srv = servers.get(agent_id)
            if not srv:
                continue
            _names = {**DEFAULT_AGENT_NAMES, **_load_agent_config().get("names", {})}
            agent_info = _names.get(agent_id, agent_id)

            ctx_lines = [f"【讨论主题】{topic}", ""]
            for h in history[-10:]:
                ctx_lines.append(f"【{h['name']}】{h['content'][:400]}")
            ctx_lines.append(f"\n请你以 {agent_info} 的身份，就以上讨论发表你的观点或补充意见（200字以内）。")
            prompt = "\n".join(ctx_lines)

            t0 = _time.time()
            try:
                output = await srv.worker.run(prompt)
                if isinstance(output, dict):
                    output = output.get("summary", output.get("content", str(output)))
            except Exception as e:
                output = f"[错误: {e}]"

            entry = {
                "agent":   agent_id,
                "name":    agent_info,
                "content": output,
                "round":   rnd + 1,
                "elapsed": round(_time.time() - t0, 1),
            }
            history.append(entry)
            messages.append(entry)

    return web.json_response({"messages": messages, "ok": True}, headers=CORS_HEADERS)


def register(app):
    # 工作流
    app.router.add_get("/workflow/list",         workflow_list_handler)
    app.router.add_post("/workflow/save",        workflow_save_handler)
    app.router.add_post("/workflow/run",         workflow_run_handler)
    app.router.add_post("/workflow/ai_build",    workflow_ai_build_handler)
    app.router.add_get("/ws/workflow",           workflow_ws_handler)
    app.router.add_delete("/workflow/{wf_id}",   workflow_delete_handler)
    # 定时任务
    app.router.add_get("/scheduler/tasks",                       sched_list_handler)
    app.router.add_get("/scheduler/logs",                        sched_logs_handler)
    app.router.add_post("/scheduler/tasks",                      sched_add_handler)
    app.router.add_post("/scheduler/tasks/{task_id}/toggle",     sched_toggle_handler)
    app.router.add_post("/scheduler/tasks/{task_id}/run",        sched_run_now_handler)
    app.router.add_delete("/scheduler/tasks/{task_id}",          sched_delete_handler)
    # 文件监视器
    app.router.add_get("/watcher/rules",                    fw_list_handler)
    app.router.add_get("/watcher/events",                   fw_events_handler)
    app.router.add_post("/watcher/rules",                   fw_add_handler)
    app.router.add_post("/watcher/rules/{rule_id}/toggle",  fw_toggle_handler)
    app.router.add_delete("/watcher/rules/{rule_id}",       fw_delete_handler)
    # 群聊
    app.router.add_post("/groupchat/run",                   groupchat_run_handler)
