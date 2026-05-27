"""
routes/workflow.py — 工作流 CRUD + 定时任务 + 文件监视器 + 群聊 + 执行引擎
"""
import asyncio
import json
import time as _time
from aiohttp import web

from .auth import CORS_HEADERS
from knowledge_base import kb as _kb
from scheduler import scheduler as _scheduler
from file_watcher import watcher as _watcher


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


async def workflow_delete_handler(request):
    """DELETE /workflow/{wf_id}"""
    wf_id = request.match_info["wf_id"]
    wm = request.app["workflow_mgr"]
    ok = wm.delete_workflow(wf_id)
    return web.json_response({"deleted": ok}, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  工作流执行引擎
# ══════════════════════════════════════════════════════

async def _run_step(srv, full_prompt: str) -> tuple:
    """安全执行单个 Agent 步骤"""
    t0 = _time.time()
    try:
        result = await srv.worker.run(full_prompt)
        elapsed = round(_time.time() - t0, 1)
        if isinstance(result, dict):
            output = result.get("summary") or result.get("content") or str(result)
        else:
            output = str(result)
    except Exception as e:
        output  = f"执行错误: {e}"
        elapsed = round(_time.time() - t0, 1)
    return output, elapsed


async def workflow_run_handler(request):
    """POST /workflow/run — 执行工作流步骤

    支持节点类型:
      sequential（默认）— 顺序执行
      parallel            — 并行执行多个 Agent
      condition           — 根据关键词选择分支
      loop                — 循环直到满足条件
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

    results     = []
    prev_output = ""

    async def exec_single(step_def: dict, step_idx: int, ctx: str) -> dict:
        """执行单个 sequential 步骤"""
        agent_id = step_def.get("agent", "xi")
        prompt   = step_def.get("prompt", "").strip()
        pass_ctx = step_def.get("pass_context", True)
        if not prompt:
            return {"step": step_idx, "agent": agent_id,
                    "output": "(跳过：提示词为空)", "elapsed": 0, "type": "sequential"}
        srv = servers.get(agent_id)
        if not srv:
            return {"step": step_idx, "agent": agent_id,
                    "output": f"错误：未知 agent {agent_id}", "elapsed": 0, "type": "sequential"}
        full_prompt = prompt
        if pass_ctx and ctx:
            full_prompt = f"【上一步输出】\n{ctx}\n\n【当前任务】\n{prompt}"
        if use_kb:
            kb_ctx = await asyncio.to_thread(_kb.build_context, prompt, 3)
            if kb_ctx:
                full_prompt = kb_ctx + "\n\n" + full_prompt
        output, elapsed = await _run_step(srv, full_prompt)
        return {"step": step_idx, "agent": agent_id, "output": output,
                "elapsed": elapsed, "prompt": prompt, "type": "sequential"}

    for i, step in enumerate(steps):
        node_type = step.get("type", "sequential")

        if node_type == "parallel":
            branches = step.get("branches", [])
            if not branches:
                results.append({"step": i+1, "type": "parallel",
                                "output": "(并行节点无分支)", "elapsed": 0})
                continue
            t0 = _time.time()
            tasks = [exec_single(b, i+1, prev_output) for b in branches]
            branch_results = await asyncio.gather(*tasks, return_exceptions=True)
            elapsed = round(_time.time() - t0, 1)
            outputs = []
            for br in branch_results:
                if isinstance(br, dict):
                    outputs.append(f"[{br['agent']}] {br['output']}")
                elif isinstance(br, Exception):
                    outputs.append(f"[错误] {br}")
            combined = "\n\n---\n\n".join(outputs)
            prev_output = combined
            results.append({
                "step": i+1, "type": "parallel",
                "output": combined, "elapsed": elapsed,
                "branches": [br for br in branch_results if isinstance(br, dict)],
            })

        elif node_type == "condition":
            keyword    = step.get("keyword", "")
            true_step  = step.get("true_step")
            false_step = step.get("false_step")
            matched    = keyword.lower() in prev_output.lower() if keyword else False
            chosen     = true_step if matched else false_step
            if not chosen:
                results.append({"step": i+1, "type": "condition",
                                "output": f"(条件 '{keyword}' {'满足' if matched else '不满足'}，无对应分支)",
                                "matched": matched, "elapsed": 0})
                continue
            r = await exec_single(chosen, i+1, prev_output)
            r["type"]    = "condition"
            r["keyword"] = keyword
            r["matched"] = matched
            prev_output  = r["output"]
            results.append(r)

        elif node_type == "loop":
            max_iter   = int(step.get("max_iter", 3))
            stop_word  = step.get("stop_keyword", "完成")
            inner_step = step.get("step")
            if not inner_step:
                results.append({"step": i+1, "type": "loop",
                                "output": "(循环节点缺少 step 定义)", "elapsed": 0})
                continue
            t0 = _time.time()
            loop_output = prev_output
            iteration = 0
            for iteration in range(max_iter):
                r = await exec_single(inner_step, i+1, loop_output)
                loop_output = r["output"]
                if stop_word.lower() in loop_output.lower():
                    break
            elapsed = round(_time.time() - t0, 1)
            prev_output = loop_output
            results.append({"step": i+1, "type": "loop", "output": loop_output,
                            "elapsed": elapsed, "iterations": iteration+1})

        else:
            r = await exec_single(step, i+1, prev_output)
            prev_output = r["output"]
            results.append(r)

    return web.json_response({"results": results, "ok": True}, headers=CORS_HEADERS)


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
