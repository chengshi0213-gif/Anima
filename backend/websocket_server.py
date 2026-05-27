#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket 通信层 — Anima
Tauri 桌面壳 ↔ Python 后端的桥梁

三个员工: Anima/晞/陶朱，共用 PORT_WS 端口
同时提供 /health /usage /console HTTP 路由
"""
import sys, json, asyncio
from pathlib import Path
from datetime import datetime

# 确保能找到同目录的模块
sys.path.insert(0, str(Path(__file__).parent))

import aiohttp
from aiohttp import web

from config import (
    PORT_WS, LOG_DIR, SESSIONS_DB, WORKFLOWS_DIR, BACKEND_DIR,
    save_user_config, is_configured,
    DEEPSEEK_KEY, KIMI_KEY, QWEN_KEY, OPENAI_KEY, ANTHROPIC_KEY,
    OPENROUTER_KEY, GLM_KEY, GEMINI_KEY,
)
from xi_worker import XiWorker
from yiyi_worker import YiyiWorker
from tianyuan_worker import TianyuanWorker
from scholar_worker import ShoucangWorker
from executor_worker import ExecutorWorker
from writer_worker import WriterWorker
from reader_worker import ReaderWorker
from critic_worker import CriticWorker
from search_engine import SearchEngine
from workflow_manager import WorkflowManager
from usage_tracker import UsageTracker
from knowledge_base import kb as _kb
from scheduler import scheduler as _scheduler
from file_watcher import watcher as _watcher
import notifier as _notifier
from skill_manager import (
    list_skills, get_skill, record_usage, upgrade_skill,
    install_community_skill, get_skills_summary, init_builtin_skills,
)
from onboarding import (
    is_ftue_done, mark_ftue_done, get_welcome_message, get_shoucang_first_run_prompt
)
from report_generator import (
    get_or_generate_report, get_latest_report,
    should_send_daily, should_send_weekly,
)
from agent_base import PermissionRequest

# 协议: Client→Server {"action":"chat|status|search|workflow_*|usage_*|cancel", ...}
#       Server→Client {"type":"response|error|status", "data":...}

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def _json_error(message: str, status: int = 400) -> web.Response:
    """统一错误响应格式: {"error": "..."}，带 CORS 头"""
    return web.json_response({"error": message}, status=status, headers=CORS_HEADERS)


# ── 本地安全 Token ──────────────────────────────────────────────
# 保护端口不被局域网/恶意脚本滥用。
# Tauri 前端和 CLI 工具在本地运行，token 从文件读取即可。
# 从外部 IP 访问时必须携带 Authorization: Bearer <token>。

import secrets as _secrets
import ipaddress as _ipaddress

_TOKEN_FILE = Path.home() / ".anima" / "local_token.txt"

def _load_or_create_token() -> str:
    if _TOKEN_FILE.exists():
        try:
            tok = _TOKEN_FILE.read_text("utf-8").strip()
            if len(tok) >= 32:
                return tok
        except Exception:
            pass
    tok = _secrets.token_urlsafe(32)
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(tok, "utf-8")
    return tok

LOCAL_TOKEN: str = _load_or_create_token()

def _is_local(request) -> bool:
    """判断是否为本地请求（127.x 或 ::1）"""
    peer = request.transport.get_extra_info("peername")
    if not peer:
        return True
    try:
        addr = _ipaddress.ip_address(peer[0])
        return addr.is_loopback
    except Exception:
        return True

def _check_token(request) -> bool:
    """非本地请求必须携带正确 token。本地请求始终放行。"""
    if _is_local(request):
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip() == LOCAL_TOKEN
    return False

@web.middleware
async def auth_middleware(request, handler):
    """鉴权中间件：OPTIONS 和 /health 跳过；其他非本地请求验证 token"""
    if request.method == "OPTIONS":
        return await handler(request)
    if request.path in ("/health", "/docs", "/openapi.json"):
        return await handler(request)
    if not _check_token(request):
        return web.json_response(
            {"error": "unauthorized — include Authorization: Bearer <local_token>"},
            status=401, headers=CORS_HEADERS,
        )
    return await handler(request)


class WorkerServer:
    def __init__(self, worker, search_engine, workflow_mgr, usage_tracker):
        self.worker = worker
        self.search = search_engine
        self.workflow = workflow_mgr
        self.usage = usage_tracker
        self.current_task = None
        self.current_session_id = None

    async def handle(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "无效 JSON"})
                continue
            action = data.get("action", "")
            try:
                handlers = {
                    "chat":              self._handle_chat,
                    "status":            self._handle_status,
                    "search":            self._handle_search,
                    "workflow_save":     self._handle_workflow_save,
                    "workflow_list":     self._handle_workflow_list,
                    "workflow_load":     self._handle_workflow_load,
                    "workflow_delete":   self._handle_workflow_delete,
                    "usage_daily":       self._handle_usage_daily,
                    "usage_agents":      self._handle_usage_agents,
                    "usage_projection":  self._handle_usage_projection,
                    "cancel":            self._handle_cancel,
                }
                handler = handlers.get(action)
                if handler:
                    await handler(ws, data)
                else:
                    await ws.send_json({"type": "error", "message": f"未知 action: {action}"})
            except Exception as e:
                await ws.send_json({"type": "error", "message": str(e)})
        return ws

    async def _handle_chat(self, ws, data):
        message = data.get("message", "")
        files   = data.get("files", [])   # [{name, content, type}]

        # 将上传的文件内容拼入消息上下文（和 Claude 一样，content 在前）
        if files:
            file_blocks = []
            for f in files:
                name    = f.get("name", "file")
                content = f.get("content", "")
                if content:
                    file_blocks.append(f"[附件: {name}]\n{content}")
            if file_blocks:
                file_ctx = "\n\n---\n\n".join(file_blocks)
                message  = f"{file_ctx}\n\n---\n\n{message}" if message.strip() else file_ctx

        if not message.strip():
            await ws.send_json({"type": "error", "message": "消息为空"})
            return
        # 前端传来的显示名（如 "DeepSeek-V4-Flash"），worker 内部路由
        selected_model = data.get("model") or None
        session_id = data.get("session_id") or f"{self.worker.name}-{int(asyncio.get_event_loop().time())}"
        self.current_session_id = session_id
        await ws.send_json({"type": "status", "status": "running",
                            "session_id": session_id, "model": selected_model})
        try:
            result = await self.worker.run(message, session_id=session_id, model=selected_model, ws=ws)
        except PermissionRequest as pr:
            await ws.send_json({
                "type": "permission_request",
                "data": {
                    "api_name":    pr.api_name,
                    "reason":      pr.reason,
                    "signup_url":  pr.signup_url,
                    "alternatives": pr.alternatives,
                    "related":     pr.related,
                }
            })
            return
        self.search.index_session(session_id, self.worker.name, [
            {"role": "user", "content": message},
            {"role": "assistant", "content": result.get("summary", "")},
        ])
        await ws.send_json({"type": "response", "data": {
            "session_id":    session_id,
            "status":        result["status"],
            "summary":       result.get("summary", ""),
            "model":         selected_model or self.worker.model,
            "files_changed": result.get("files_changed", []),
            "turn_count":    result.get("turn_count", 0),
        }})

    async def _handle_status(self, ws, data=None):
        await ws.send_json({"type": "response", "data": {
            "agent":           self.worker.name,
            "model":           self.worker.model,
            "tools":           len(self.worker.tool_defs),
            "current_session": self.current_session_id,
            "busy":            self.current_task is not None and not self.current_task.done(),
        }})

    async def _handle_search(self, ws, data):
        query = data.get("query", "")
        if not query:
            await ws.send_json({"type": "error", "message": "搜索词为空"})
            return
        results = self.search.search(query, agent=data.get("agent"))
        await ws.send_json({"type": "response", "data": {"query": query, "results": results}})

    async def _handle_workflow_save(self, ws, data):
        name = data.get("name", ""); prompt = data.get("prompt", "")
        if not name or not prompt:
            await ws.send_json({"type": "error", "message": "需要 name 和 prompt"})
            return
        result = self.workflow.save(name, prompt, self.worker.name)
        await ws.send_json({"type": "response", "data": result})

    async def _handle_workflow_list(self, ws, data):
        await ws.send_json({"type": "response", "data": {"workflows": self.workflow.list_all()}})

    async def _handle_workflow_load(self, ws, data):
        name = data.get("name", "")
        if not name:
            await ws.send_json({"type": "error", "message": "需要 name"}); return
        tmpl = self.workflow.load(name)
        if tmpl is None:
            await ws.send_json({"type": "error", "message": f"模板不存在: {name}"}); return
        await ws.send_json({"type": "response", "data": tmpl})

    async def _handle_workflow_delete(self, ws, data):
        ok = self.workflow.delete(data.get("name", ""))
        await ws.send_json({"type": "response", "data": {"deleted": ok}})

    async def _handle_usage_daily(self, ws, data):
        await ws.send_json({"type": "response", "data":
            self.usage.get_daily_stats(days=data.get("days", 7))})

    async def _handle_usage_agents(self, ws, data):
        await ws.send_json({"type": "response", "data":
            self.usage.get_per_agent_stats(days=data.get("days", 7))})

    async def _handle_usage_projection(self, ws, data):
        await ws.send_json({"type": "response", "data": self.usage.get_monthly_projection()})

    async def _handle_cancel(self, ws, data=None):
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
        self.current_session_id = None
        await ws.send_json({"type": "response", "data": {"cancelled": True}})


# ═══════════════════════════════════════════════════
#  HTTP 路由
# ═══════════════════════════════════════════════════

async def health_handler(request):
    """GET /health — 健康检查（Tauri 前端用于判断后端是否就绪）
    本地请求额外返回 local_token，让前端自动保存。
    """
    payload: dict = {"status": "ok", "timestamp": datetime.now().isoformat()}
    # 仅对本地请求暴露 token（前端存入 localStorage 用于后续鉴权）
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
    """GET /console — 兼容旧版（已由前端原生渲染取代）"""
    return web.json_response({"deprecated": True, "message": "Use native overview panel"}, headers=CORS_HEADERS)


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


# ══════════════════════════════════════════════════════
#  知识库 HTTP 接口
# ══════════════════════════════════════════════════════

async def kb_docs_handler(request):
    """GET /kb/docs — 列出所有文档"""
    docs = await asyncio.to_thread(_kb.list_docs)
    return web.json_response({"docs": docs}, headers=CORS_HEADERS)


async def kb_search_handler(request):
    """POST /kb/search — 语义检索
    Body: {"query": "...", "top_k": 5, "doc_id": null}
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    query  = body.get("query", "").strip()
    top_k  = int(body.get("top_k", 5))
    doc_id = body.get("doc_id") or None
    if not query:
        return web.json_response({"error": "query is empty"}, status=400, headers=CORS_HEADERS)
    try:
        hits = await asyncio.to_thread(_kb.search, query, top_k, doc_id)
        return web.json_response({"hits": hits}, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


async def kb_upload_handler(request):
    """POST /kb/upload — 上传并入库文件
    multipart/form-data: file=<binary>, name=<display_name>
    或 JSON: {"text": "...", "name": "..."}
    """
    ct = request.content_type or ""
    try:
        if "multipart" in ct:
            reader = await request.multipart()
            text, name = "", ""
            async for part in reader:
                if part.name == "file":
                    raw = await part.read()
                    name = name or part.filename or "未命名文件"
                    try:
                        text = raw.decode("utf-8", errors="replace")
                    except Exception:
                        text = raw.decode("latin-1", errors="replace")
                elif part.name == "name":
                    name = (await part.read()).decode("utf-8", errors="replace")
        else:
            body = await request.json()
            text = body.get("text", "")
            name = body.get("name", "粘贴内容")

        if not text.strip():
            return web.json_response({"error": "文件内容为空"}, status=400, headers=CORS_HEADERS)

        result = await asyncio.to_thread(_kb.ingest, text, name)
        return web.json_response(result, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


async def kb_delete_handler(request):
    """DELETE /kb/docs/{doc_id} — 删除文档"""
    doc_id = request.match_info["doc_id"]
    result = await asyncio.to_thread(_kb.delete, doc_id)
    if "error" in result:
        return web.json_response(result, status=404, headers=CORS_HEADERS)
    return web.json_response(result, headers=CORS_HEADERS)


async def kb_options_handler(request):
    return web.Response(headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  工作流接口
# ══════════════════════════════════════════════════════

async def workflow_list_handler(request):
    """GET /workflow/list — 列出已保存工作流"""
    wm = request.app["workflow_mgr"]
    items = wm.list_all()
    return web.json_response({"workflows": items}, headers=CORS_HEADERS)


async def workflow_save_handler(request):
    """POST /workflow/save — 保存工作流定义
    Body: {"id":"...", "name":"...", "steps":[{agent,prompt,pass_context}]}
    """
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


async def sched_list_handler(request):
    """GET /scheduler/tasks"""
    return web.json_response({"tasks": _scheduler.list_tasks()}, headers=CORS_HEADERS)

async def sched_logs_handler(request):
    """GET /scheduler/logs?task_id=&limit=50"""
    task_id = request.query.get("task_id") or None
    limit   = int(request.query.get("limit", 50))
    return web.json_response({"logs": _scheduler.list_logs(task_id, limit)}, headers=CORS_HEADERS)

async def sched_add_handler(request):
    """POST /scheduler/tasks
    Body: {name, agent, prompt, trigger_type, trigger_value}
    """
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


async def _run_step(srv, full_prompt: str) -> str:
    """安全执行单个 Agent 步骤（AgentBase.run 是协程）"""
    import time as _time
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
      sequential（默认）— 顺序执行，前一步输出传给下一步
      parallel            — 并行执行多个 Agent，结果合并后继续
      condition           — 根据上一步输出关键词选择分支

    Body:
    {
      "steps": [
        {"agent":"xi", "prompt":"…", "pass_context":true, "type":"sequential"},
        {"type":"parallel", "branches":[
          {"agent":"writer",   "prompt":"…"},
          {"agent":"reader",   "prompt":"…"}
        ]},
        {"type":"condition", "keyword":"失败",
         "true_step":  {"agent":"xi", "prompt":"处理失败情况…"},
         "false_step": {"agent":"xi", "prompt":"继续正常流程…"}
        }
      ],
      "use_kb": false
    }
    """
    import time as _time
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
        """执行单个 sequential 步骤，返回 result dict"""
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
            # ── 并行节点：同时运行多个 Agent ─────────────────────────
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
            # ── 条件节点：根据上一步输出选分支 ────────────────────────
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
            # ── 循环节点：最多执行 N 次，直到输出包含停止关键词 ────────
            max_iter   = int(step.get("max_iter", 3))
            stop_word  = step.get("stop_keyword", "完成")
            inner_step = step.get("step")
            if not inner_step:
                results.append({"step": i+1, "type": "loop",
                                "output": "(循环节点缺少 step 定义)", "elapsed": 0})
                continue
            t0 = _time.time()
            loop_output = prev_output
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
            # ── 顺序节点（默认）────────────────────────────────────────
            r = await exec_single(step, i+1, prev_output)
            prev_output = r["output"]
            results.append(r)

    return web.json_response({"results": results, "ok": True}, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  TTS 接口（edge-tts）
# ══════════════════════════════════════════════════════

# Agent 默认音色映射（edge-tts 声音）
AGENT_VOICES = {
    "xi":   "zh-CN-YunxiNeural",      # 磁性男声
    "yiyi":     "zh-CN-XiaoxiaoNeural",   # 温柔女声
    "tianyuan": "zh-CN-YunyangNeural",    # 沉稳男声
    "shoucang": "zh-CN-YunjianNeural",    # 儒雅男声
    "executor": "zh-CN-YunxiNeural",
    "writer":   "zh-CN-XiaoyiNeural",
    "reader":   "zh-CN-YunjianNeural",
    "critic":   "zh-CN-YunyangNeural",
}

async def tts_handler(request):
    """POST /tts — 文字转语音
    Body: {"text": "...", "agent": "xi", "voice": "zh-CN-XiaoxiaoNeural"}
    Response: audio/mpeg binary
    """
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text="invalid json")

    text  = body.get("text", "").strip()[:500]  # 限制长度
    agent = body.get("agent", "xi")
    voice = body.get("voice") or AGENT_VOICES.get(agent, "zh-CN-YunxiNeural")

    if not text:
        return web.Response(status=400, text="text is empty")

    try:
        import edge_tts
        import io
        buf = io.BytesIO()
        communicate = edge_tts.Communicate(text, voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        buf.seek(0)
        audio_data = buf.read()
        if not audio_data:
            return web.Response(status=500, text="TTS 生成为空")
        return web.Response(
            body=audio_data,
            content_type="audio/mpeg",
            headers={**CORS_HEADERS, "Cache-Control": "no-store"},
        )
    except ImportError:
        return web.Response(status=501, text="edge-tts 未安装，请运行: pip install edge-tts")
    except Exception as e:
        return web.Response(status=500, text=f"TTS 错误: {e}")


async def tts_voices_handler(request):
    """GET /tts/voices — 返回 Agent 音色配置"""
    import config as _cfg_mod
    cfg = _load_agent_config()
    result = {}
    for agent_id, default_voice in AGENT_VOICES.items():
        result[agent_id] = cfg.get("voices", {}).get(agent_id, default_voice)
    return web.json_response({"voices": result}, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  Agent 配置接口（名称 / 音色 / 头像）
# ══════════════════════════════════════════════════════

_AGENT_CFG_FILE = None   # 延迟初始化（DATA_DIR 在 config 加载后才确定）

def _agent_cfg_file():
    from config import DATA_DIR
    return DATA_DIR.parent / "agent_config.json"  # ~/.anima/agent_config.json

def _load_agent_config() -> dict:
    f = _agent_cfg_file()
    if f.exists():
        import json as _json
        return _json.loads(f.read_text("utf-8"))
    return {}

def _save_agent_config(data: dict):
    import json as _json
    f = _agent_cfg_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

DEFAULT_AGENT_NAMES = {
    "xi":       "Anima",
    "yiyi":     "晞",
    "tianyuan": "陶朱",
    "shoucang": "守藏",
    "executor": "执行者",
    "writer":   "写手",
    "reader":   "阅读者",
    "critic":   "评审",
}

async def agent_config_get(request):
    """GET /config/agents — 返回 agent 名称 / 音色 / 描述"""
    cfg = _load_agent_config()
    names  = {**DEFAULT_AGENT_NAMES, **cfg.get("names", {})}
    voices = {**AGENT_VOICES,        **cfg.get("voices", {})}
    return web.json_response({"names": names, "voices": voices}, headers=CORS_HEADERS)

async def agent_config_set(request):
    """POST /config/agents — 保存 agent 名称 / 音色
    Body: {"names": {"xi":"xi",...}, "voices": {"xi":"zh-CN-...",...}}
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    cfg = _load_agent_config()
    if "names"  in body: cfg["names"]  = {**cfg.get("names",{}),  **body["names"]}
    if "voices" in body: cfg["voices"] = {**cfg.get("voices",{}), **body["voices"]}
    _save_agent_config(cfg)
    return web.json_response({"ok": True, "config": cfg}, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  Onboarding / 初始化配置接口
# ══════════════════════════════════════════════════════

async def setup_status_handler(request):
    """GET /setup/status — 是否已完成初始配置"""
    import config as _cfg_mod
    cfg = _load_agent_config()
    # Read per-agent user address from config
    user_cfg = _cfg_mod._cfg.get("user", {}) if hasattr(_cfg_mod, "_cfg") else {}
    user_address = user_cfg.get("address", {})
    return web.json_response({
        "configured": _cfg_mod.is_configured(),
        "ftue_done":  is_ftue_done(),
        "agent_names": {**DEFAULT_AGENT_NAMES, **cfg.get("names", {})},
        "user_address": user_address,
        "keys": {
            "deepseek":  bool(_cfg_mod.DEEPSEEK_KEY and not _cfg_mod.DEEPSEEK_KEY.startswith("sk-xxx")),
            "kimi":      bool(_cfg_mod.KIMI_KEY      and not _cfg_mod.KIMI_KEY.startswith("sk-xxx")),
            "qwen":      bool(_cfg_mod.QWEN_KEY      and not _cfg_mod.QWEN_KEY.startswith("sk-xxx")),
            "openai":    bool(_cfg_mod.OPENAI_KEY    and not _cfg_mod.OPENAI_KEY.startswith("sk-xxx")),
        }
    }, headers=CORS_HEADERS)

async def setup_save_handler(request):
    """POST /setup/save — 保存初始配置（Onboarding 用）
    Body: {
      "api": {"deepseek_key":"...","kimi_key":"...","qwen_key":"..."},
      "agent_names": {"xi":"...","yiyi":"...",...},
      "user_address": {"xi":"老板","yiyi":"小宝","tianyuan":"投资人","shoucang":"守藏"},
      "lang": "zh"
    }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)

    import config as _cfg_mod

    # 保存 API keys
    api_updates = body.get("api", {})
    if api_updates:
        _cfg_mod.save_user_config({"api": api_updates})
        # 刷新运行时的 key
        for attr, key in [
            ("DEEPSEEK_KEY","deepseek_key"),("KIMI_KEY","kimi_key"),
            ("QWEN_KEY","qwen_key"),("OPENAI_KEY","openai_key"),
            ("ANTHROPIC_KEY","anthropic_key"),("OPENROUTER_KEY","openrouter_key"),
        ]:
            v = api_updates.get(key)
            if v: setattr(_cfg_mod, attr, v)

    # 保存语言偏好
    if "lang" in body:
        _cfg_mod.save_user_config({"lang": body["lang"]})

    # 保存 agent 名称
    if "agent_names" in body:
        cfg = _load_agent_config()
        cfg["names"] = {**cfg.get("names", {}), **body["agent_names"]}
        _save_agent_config(cfg)

    # 保存 per-agent 用户称呼（user.address.*）
    # 空字符串表示清除该项；不在请求体里则不改动
    raw_address = body.get("user_address")
    if raw_address is not None:
        # 过滤掉空值，只保留非空称呼
        cleaned = {k: v for k, v in raw_address.items() if v and v.strip()}
        _cfg_mod.save_user_config({"user": {"address": cleaned}})
        _cfg_mod.reload_user_config()

    # FTUE：标记完成，触发守藏初始化 SOP（后台）
    if not is_ftue_done():
        mark_ftue_done(body.get("agent_names", {}))
        shoucang = servers_ref.get("shoucang") if hasattr(servers_ref, 'get') else None
        # servers_ref 在 main() 里设置
        pass

    return web.json_response({"ok": True}, headers=CORS_HEADERS)


async def setup_welcome_handler(request):
    """GET /setup/welcome — 返回 FTUE 欢迎消息（首次配置完成后调用）"""
    import config as _cfg_mod
    cfg = _load_agent_config()
    names = {**DEFAULT_AGENT_NAMES, **cfg.get("names", {})}
    done = is_ftue_done()
    return web.json_response({
        "is_first_run": not done,
        "welcome_message": get_welcome_message(names) if not done else None,
    }, headers=CORS_HEADERS)


async def setup_complete_handler(request):
    """POST /setup/complete — 标记 FTUE 完成，触发守藏初始化 SOP"""
    servers = request.app["servers"]
    cfg = _load_agent_config()
    names = {**DEFAULT_AGENT_NAMES, **cfg.get("names", {})}

    already_done = is_ftue_done()
    if not already_done:
        mark_ftue_done(names)
        # 后台触发守藏初始化 SOP（AgentBase.run 是协程，直接 create_task）
        shoucang = servers.get("shoucang")
        if shoucang:
            init_prompt = get_shoucang_first_run_prompt()
            asyncio.create_task(shoucang.worker.run(init_prompt))

    return web.json_response({
        "ok": True,
        "welcome_message": get_welcome_message(names),
        "first_run": not already_done,
    }, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  Skill HTTP 接口
# ══════════════════════════════════════════════════════

async def skills_list_handler(request):
    """GET /skills — 列出所有 Skill"""
    category = request.query.get("category") or None
    skills = await asyncio.to_thread(list_skills, category)
    summary = await asyncio.to_thread(get_skills_summary)
    return web.json_response({"skills": skills, "summary": summary}, headers=CORS_HEADERS)

async def skill_get_handler(request):
    """GET /skills/{skill_id}"""
    sid = request.match_info["skill_id"]
    skill = await asyncio.to_thread(get_skill, sid)
    if not skill:
        return web.json_response({"error": "Skill 不存在"}, status=404, headers=CORS_HEADERS)
    return web.json_response(skill, headers=CORS_HEADERS)

async def skill_record_usage_handler(request):
    """POST /skills/{skill_id}/usage  body: {score: 4.5}"""
    sid = request.match_info["skill_id"]
    try:
        body = await request.json()
        score = body.get("score")
    except Exception:
        score = None
    await asyncio.to_thread(record_usage, sid, score)
    return web.json_response({"ok": True}, headers=CORS_HEADERS)

async def skill_upgrade_handler(request):
    """POST /skills/{skill_id}/upgrade  body: {new_prompt, note, weak_points}"""
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
    """POST /skills/install  body: {url: "github:user/repo"}"""
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
    """GET /membership/status — 获取当前会员状态"""
    from membership import get_membership
    return web.json_response(get_membership(), headers=CORS_HEADERS)


async def membership_activate_handler(request):
    """POST /membership/activate — 激活会员（body: {"code": "ANIMA-..."}）"""
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
    """POST /membership/deactivate — 取消激活（退回免费）"""
    from membership import deactivate
    result = deactivate()
    return web.json_response(result, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  日报 / 周报 HTTP 接口
# ══════════════════════════════════════════════════════

async def report_status_handler(request):
    """GET /reports/status — 是否应发送报告"""
    return web.json_response({
        "send_daily":  should_send_daily(),
        "send_weekly": should_send_weekly(),
    }, headers=CORS_HEADERS)

async def report_daily_handler(request):
    """GET /reports/daily — 获取或生成日报"""
    force = request.query.get("force") == "1"
    if force:
        from report_generator import generate_daily_report
        report = await asyncio.to_thread(generate_daily_report)
    else:
        report = await get_or_generate_report("daily")
    return web.json_response(report or {}, headers=CORS_HEADERS)

async def report_weekly_handler(request):
    """GET /reports/weekly — 获取或生成周报"""
    force = request.query.get("force") == "1"
    if force:
        from report_generator import generate_weekly_report
        report = await asyncio.to_thread(generate_weekly_report)
    else:
        report = await get_or_generate_report("weekly")
    return web.json_response(report or {}, headers=CORS_HEADERS)


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
    # Vault 写入后立即使记忆缓存失效
    try:
        from memory_injector import invalidate_cache
        invalidate_cache()
    except Exception:
        pass
    return web.json_response(result, headers=CORS_HEADERS)


async def memory_learn_handler(request):
    """POST /memory/learn — 「Anima 记住了」快捷写入
    body: {key, value, agent?, category?, importance?}
    同时兼容 SQLite 和 Obsidian 后端。
    """
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
    """POST /memory/backend — 切换后端
    body: {backend: "sqlite"|"obsidian", obsidian_path?: str, migrate?: bool}
    """
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
    """POST /memory/migrate — 迁移数据（不切换激活后端）
    body: {to: "sqlite"|"obsidian", obsidian_path?: str, merge?: bool}
    """
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
    """POST /projects — 创建项目  body: {name, description?}"""
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


async def shoucang_sop_handler(request):
    """POST /shoucang/sop — 触发守藏日常 SOP（后台异步，SSE 进度推送）"""
    servers = request.app["servers"]
    shoucang_server = servers.get("shoucang")
    if not shoucang_server:
        return web.json_response({"error": "守藏 worker 未就绪"}, status=503, headers=CORS_HEADERS)

    # 用 SSE 推送进度
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    if body.get("stream"):
        # SSE 模式：保持连接，推送进度
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
        # 等待 SOP 完成（最长 10 分钟），完成后立即关闭连接
        try:
            await asyncio.wait_for(done_event.wait(), timeout=600)
        except asyncio.TimeoutError:
            pass
        await push(0, 0, "SOP 执行完成")
        await resp.write_eof()
        return resp
    else:
        # 普通模式：立即返回，后台执行
        asyncio.create_task(asyncio.to_thread(shoucang_server.worker.run_daily_sop))
        return web.json_response({"ok": True, "message": "SOP 已在后台启动"}, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  API 配置接口（丰富化）
# ══════════════════════════════════════════════════════

# 所有支持的 API 定义
API_CATALOG = [
    # LLM
    {"id":"deepseek",  "name":"DeepSeek",     "category":"llm",    "icon":"🔵",
     "desc":"Anima + 陶朱主脑，国内最强编程推理模型",
     "signup_url":"https://platform.deepseek.com",  "config_key":"deepseek_key",  "required":True},
    {"id":"kimi",      "name":"Kimi",          "category":"llm",    "icon":"🌙",
     "desc":"陶朱团队写手/阅读者，超长上下文（128K）",
     "signup_url":"https://platform.moonshot.cn",   "config_key":"kimi_key",      "required":True},
    {"id":"qwen",      "name":"通义千问",       "category":"llm",    "icon":"🟢",
     "desc":"知识库 Embedding + 守藏检索增强",
     "signup_url":"https://dashscope.aliyun.com",   "config_key":"qwen_key",      "required":False},
    {"id":"openai",    "name":"OpenAI",         "category":"llm",    "icon":"⚫",
     "desc":"GPT 系列模型（可选）",
     "signup_url":"https://platform.openai.com",    "config_key":"openai_key",    "required":False},
    {"id":"anthropic", "name":"Anthropic",      "category":"llm",    "icon":"🟤",
     "desc":"Claude 系列模型（可选）",
     "signup_url":"https://console.anthropic.com",  "config_key":"anthropic_key", "required":False},
    {"id":"openrouter","name":"OpenRouter",     "category":"llm",    "icon":"🔀",
     "desc":"统一路由（Claude/GPT 中转），多模型备用",
     "signup_url":"https://openrouter.ai",          "config_key":"openrouter_key","required":False},
    # 搜索 & 网络
    {"id":"tavily",    "name":"Tavily Search",  "category":"search", "icon":"🔍",
     "desc":"AI 原生搜索引擎，联网搜索最推荐，免费 1000次/月",
     "signup_url":"https://tavily.com",             "config_key":"tavily_key",    "required":False},
    {"id":"serper",    "name":"Serper (Google)","category":"search", "icon":"🌐",
     "desc":"Google 搜索 API，结果最全面",
     "signup_url":"https://serper.dev",             "config_key":"serper_key",    "required":False},
    {"id":"jina",      "name":"Jina AI Reader", "category":"search", "icon":"📄",
     "desc":"网页内容读取与解析，抓取任意网页正文",
     "signup_url":"https://jina.ai",                "config_key":"jina_key",      "required":False},
    {"id":"firecrawl", "name":"Firecrawl",      "category":"search", "icon":"🕷️",
     "desc":"深度网站爬取，支持整站抓取与结构化提取",
     "signup_url":"https://firecrawl.dev",          "config_key":"firecrawl_key", "required":False},
    # 效率工具
    {"id":"github",    "name":"GitHub",         "category":"tools",  "icon":"🐙",
     "desc":"项目图谱分析、代码搜索、Issue 管理",
     "signup_url":"https://github.com/settings/tokens","config_key":"github_token","required":False},
    {"id":"smtp",      "name":"邮件 SMTP",       "category":"tools",  "icon":"📧",
     "desc":"发送邮件通知（工作流输出节点）",
     "signup_url":"",                               "config_key":"smtp_host",     "required":False},
    # 存储
    {"id":"notion",    "name":"Notion",          "category":"storage","icon":"📝",
     "desc":"同步笔记到 Notion 数据库（可选，Obsidian 优先）",
     "signup_url":"https://www.notion.so/my-integrations","config_key":"notion_key","required":False},
]

def _get_api_statuses() -> list[dict]:
    """返回所有 API 的配置状态（统一从 config.py 读取）"""
    import config as _cfg
    key_map = {
        "deepseek_key":  _cfg.DEEPSEEK_KEY,
        "kimi_key":      _cfg.KIMI_KEY,
        "qwen_key":      _cfg.QWEN_KEY,
        "openai_key":    _cfg.OPENAI_KEY,
        "anthropic_key": _cfg.ANTHROPIC_KEY,
        "openrouter_key":_cfg.OPENROUTER_KEY,
        "tavily_key":    _cfg.TAVILY_KEY,
        "serper_key":    _cfg.SERPER_KEY,
        "jina_key":      _cfg.JINA_KEY,
        "firecrawl_key": _cfg.FIRECRAWL_KEY,
        "github_token":  _cfg.GITHUB_TOKEN,
    }
    result = []
    for api in API_CATALOG:
        ck  = api["config_key"]
        val = key_map.get(ck, "")
        configured = bool(val and not val.startswith("sk-xxx") and len(val) > 4)
        result.append({**api, "configured": configured,
                        "masked_key": f"{val[:6]}…{val[-4:]}" if configured else ""})
    return result

async def webhook_trigger_handler(request):
    """POST /hook/{agent_id} — 外部 Webhook 触发 Agent 任务

    用途：CI/CD、Zapier、n8n 等外部服务触发 Anima Agent
    Body: {
        prompt: str,          # 要发给 Agent 的指令（必填）
        token?: str,          # 可选鉴权 token（与 config 中的 webhook_token 匹配）
        context?: str,        # 附加上下文
        return_result?: bool, # 是否等待结果返回（默认 false，立即返回 202）
    }
    响应:
        202 + {ok:True, task_id: str}  — 后台触发（异步）
        200 + {ok:True, result: str}   — 等待结果（同步，最长 120s）
    """
    agent_id = request.match_info.get("agent_id", "xi")
    servers  = request.app["servers"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return web.json_response({"error": "prompt required"}, status=400, headers=CORS_HEADERS)

    # 可选鉴权（config 中配置 webhook_token 才生效）
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

    # 附加 context
    context = (body.get("context") or "").strip()
    full_prompt = f"{prompt}\n\n附加上下文：\n{context}" if context else prompt

    return_result = body.get("return_result", False)
    task_id = f"hook_{agent_id}_{int(__import__('time').time())}"

    if return_result:
        # 同步模式：等待 Agent 完成
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
        # 异步模式：立即返回 202，后台执行
        asyncio.create_task(srv.worker.run(full_prompt))
        return web.json_response(
            {"ok": True, "task_id": task_id, "message": f"Agent {agent_id} 已在后台启动"},
            status=202, headers=CORS_HEADERS,
        )


async def api_catalog_handler(request):
    """GET /config/api-catalog — 所有 API 及配置状态"""
    statuses = await asyncio.to_thread(_get_api_statuses)
    return web.json_response({"apis": statuses}, headers=CORS_HEADERS)

async def api_save_handler(request):
    """POST /config/api-save  body: {deepseek_key:..., tavily_key:...}
    所有 key 统一写入 ~/.anima/config.yaml 的 api 节。
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    import config as _cfg
    # 所有允许保存的 key（白名单）
    allowed = {
        "deepseek_key", "kimi_key", "qwen_key", "openai_key",
        "anthropic_key", "openrouter_key", "glm_key", "gemini_key",
        "tavily_key", "serper_key", "jina_key", "firecrawl_key", "github_token",
        "smtp_host", "smtp_port", "smtp_user", "smtp_pass",
        "notion_key",
    }
    updates = {k: v for k, v in body.items() if k in allowed and v and not v.startswith("•")}
    if updates:
        _cfg.save_user_config({"api": updates})
        _cfg.reload_user_config()
    return web.json_response({"ok": True}, headers=CORS_HEADERS)

async def api_test_handler(request):
    """POST /config/api-test/{api_id} — 测试 API 是否可用"""
    api_id = request.match_info["api_id"]
    # 简单 ping 测试
    test_urls = {
        "deepseek":  "https://api.deepseek.com/models",
        "kimi":      "https://api.moonshot.cn/v1/models",
        "qwen":      "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
        "openai":    "https://api.openai.com/v1/models",
        "tavily":    "https://api.tavily.com/search",
    }
    url = test_urls.get(api_id)
    if not url:
        return web.json_response({"ok": False, "error": "无法测试此 API"}, headers=CORS_HEADERS)
    import config as _cfg
    key_map = {"deepseek":_cfg.DEEPSEEK_KEY,"kimi":_cfg.KIMI_KEY,
               "qwen":_cfg.QWEN_KEY,"openai":_cfg.OPENAI_KEY}
    key = key_map.get(api_id,"")
    if not key:
        return web.json_response({"ok": False, "error": "API Key 未配置"}, headers=CORS_HEADERS)
    try:
        import aiohttp as _aiohttp
        async with _aiohttp.ClientSession() as sess:
            async with sess.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=_aiohttp.ClientTimeout(total=5)) as r:
                ok = r.status in (200, 404, 422)   # 404/422 means auth passed
        return web.json_response({"ok": ok}, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, headers=CORS_HEADERS)


async def main():
    # 初始化内置 Skill（首次运行写入文件）
    await asyncio.to_thread(init_builtin_skills)

    search_engine = SearchEngine(SESSIONS_DB)
    workflow_mgr  = WorkflowManager(WORKFLOWS_DIR)
    usage_tracker = UsageTracker(LOG_DIR)

    xi_agent = XiWorker()
    yiyi     = YiyiWorker()
    tianyuan = TianyuanWorker()
    shoucang = ShoucangWorker()
    executor = ExecutorWorker()
    writer   = WriterWorker()
    reader   = ReaderWorker()
    critic   = CriticWorker()

    servers = {
        "xi":   WorkerServer(xi_agent,   search_engine, workflow_mgr, usage_tracker),
        "yiyi":     WorkerServer(yiyi,     search_engine, workflow_mgr, usage_tracker),
        "tianyuan": WorkerServer(tianyuan, search_engine, workflow_mgr, usage_tracker),
        "shoucang": WorkerServer(shoucang,  search_engine, workflow_mgr, usage_tracker),
        "executor": WorkerServer(executor, search_engine, workflow_mgr, usage_tracker),
        "writer":   WorkerServer(writer,   search_engine, workflow_mgr, usage_tracker),
        "reader":   WorkerServer(reader,   search_engine, workflow_mgr, usage_tracker),
        "critic":   WorkerServer(critic,   search_engine, workflow_mgr, usage_tracker),
    }

    app = web.Application(middlewares=[auth_middleware])
    app["search_engine"] = search_engine
    app["servers"]       = servers
    app["workflow_mgr"]  = workflow_mgr

    app.router.add_get("/ws/xi",                     servers["xi"].handle)
    app.router.add_get("/ws/yiyi",                       servers["yiyi"].handle)
    app.router.add_get("/ws/tianyuan",                   servers["tianyuan"].handle)
    app.router.add_get("/ws/shoucang",                    servers["shoucang"].handle)
    app.router.add_get("/ws/executor",                   servers["executor"].handle)
    app.router.add_get("/ws/writer",                     servers["writer"].handle)
    app.router.add_get("/ws/reader",                     servers["reader"].handle)
    app.router.add_get("/ws/critic",                     servers["critic"].handle)
    app.router.add_get("/health",                        health_handler)
    app.router.add_get("/usage",                         usage_handler)
    app.router.add_get("/status",                        status_handler)
    app.router.add_get("/sessions",                      sessions_handler)
    app.router.add_get("/sessions/{session_id}/messages", session_messages_handler)
    app.router.add_get("/console",                       console_handler)
    # 文件监视器
    async def fw_list(req):
        return web.json_response({"rules": _watcher.list_rules()}, headers=CORS_HEADERS)
    async def fw_events(req):
        rule_id = req.query.get("rule_id") or None
        limit   = int(req.query.get("limit", 50))
        return web.json_response({"events": _watcher.list_events(rule_id, limit)}, headers=CORS_HEADERS)
    async def fw_add(req):
        try:
            b = await req.json()
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
    async def fw_toggle(req):
        rule_id = req.match_info["rule_id"]
        result  = _watcher.toggle_rule(rule_id)
        return web.json_response(result, headers=CORS_HEADERS)
    async def fw_delete(req):
        rule_id = req.match_info["rule_id"]
        ok = _watcher.delete_rule(rule_id)
        return web.json_response({"deleted": ok}, headers=CORS_HEADERS)

    # 推送通知
    async def notif_list(req):
        return web.json_response({"channels": _notifier.list_channels()}, headers=CORS_HEADERS)
    async def notif_add(req):
        try: b = await req.json()
        except Exception: return web.json_response({"error":"invalid json"}, status=400, headers=CORS_HEADERS)
        ch = _notifier.add_channel(b.get("name",""), b.get("type","feishu"), b.get("webhook",""), b.get("secret",""))
        return web.json_response(ch, headers=CORS_HEADERS)
    async def notif_delete(req):
        ok = _notifier.delete_channel(req.match_info["ch_id"])
        return web.json_response({"deleted": ok}, headers=CORS_HEADERS)
    async def notif_test(req):
        ok = await asyncio.to_thread(_notifier.test_channel, req.match_info["ch_id"])
        return web.json_response({"ok": ok}, headers=CORS_HEADERS)
    async def notif_push(req):
        try: b = await req.json()
        except Exception: return web.json_response({"error":"invalid json"}, status=400, headers=CORS_HEADERS)
        results = await asyncio.to_thread(_notifier.push, b.get("title","通知"), b.get("content",""))
        return web.json_response({"results": results}, headers=CORS_HEADERS)

    app.router.add_get("/notifier/channels",              notif_list)
    app.router.add_post("/notifier/channels",             notif_add)
    app.router.add_delete("/notifier/channels/{ch_id}",   notif_delete)
    app.router.add_post("/notifier/channels/{ch_id}/test",notif_test)
    app.router.add_post("/notifier/push",                 notif_push)

    # 多 Agent 群聊
    async def groupchat_run(req):
        """POST /groupchat/run
        Body: {"topic":"...", "agents":["xi","shoucang",...], "rounds":2}
        顺序让每个 agent 发言，把所有历史作为上下文传入
        """
        try: body = await req.json()
        except Exception: return web.json_response({"error":"invalid json"}, status=400, headers=CORS_HEADERS)

        topic   = body.get("topic", "").strip()
        agents  = body.get("agents", [])
        rounds  = max(1, min(int(body.get("rounds", 1)), 3))
        if not topic: return web.json_response({"error":"topic 为空"}, status=400, headers=CORS_HEADERS)
        if not agents: return web.json_response({"error":"agents 为空"}, status=400, headers=CORS_HEADERS)

        history   = []   # [{"agent":..., "name":..., "content":...}]
        messages  = []   # 最终返回

        for rnd in range(rounds):
            for agent_id in agents:
                srv = servers.get(agent_id)
                if not srv: continue
                _names = {**DEFAULT_AGENT_NAMES, **_load_agent_config().get("names", {})}
                agent_info = _names.get(agent_id, agent_id)

                # 构建上下文
                ctx_lines = [f"【讨论主题】{topic}", ""]
                for h in history[-10:]:   # 最近10条
                    ctx_lines.append(f"【{h['name']}】{h['content'][:400]}")
                ctx_lines.append(f"\n请你以 {agent_info} 的身份，就以上讨论发表你的观点或补充意见（200字以内）。")
                prompt = "\n".join(ctx_lines)

                import time; t0 = time.time()
                try:
                    output = await srv.worker.run(prompt)
                    if isinstance(output, dict): output = output.get("summary", output.get("content", str(output)))
                except Exception as e:
                    output = f"[错误: {e}]"

                entry = {
                    "agent":   agent_id,
                    "name":    agent_info,
                    "content": output,
                    "round":   rnd + 1,
                    "elapsed": round(time.time() - t0, 1),
                }
                history.append(entry)
                messages.append(entry)

        return web.json_response({"messages": messages, "ok": True}, headers=CORS_HEADERS)

    app.router.add_post("/groupchat/run", groupchat_run)
    # 文件监视器
    app.router.add_get("/watcher/rules",                    fw_list)
    app.router.add_get("/watcher/events",                   fw_events)
    app.router.add_post("/watcher/rules",                   fw_add)
    app.router.add_post("/watcher/rules/{rule_id}/toggle",  fw_toggle)
    app.router.add_delete("/watcher/rules/{rule_id}",       fw_delete)
    # 定时任务
    app.router.add_get("/scheduler/tasks",                       sched_list_handler)
    app.router.add_get("/scheduler/logs",                        sched_logs_handler)
    app.router.add_post("/scheduler/tasks",                      sched_add_handler)
    app.router.add_post("/scheduler/tasks/{task_id}/toggle",     sched_toggle_handler)
    app.router.add_post("/scheduler/tasks/{task_id}/run",        sched_run_now_handler)
    app.router.add_delete("/scheduler/tasks/{task_id}",          sched_delete_handler)
    # 工作流
    app.router.add_get("/workflow/list",         workflow_list_handler)
    app.router.add_post("/workflow/save",        workflow_save_handler)
    app.router.add_post("/workflow/run",         workflow_run_handler)
    app.router.add_delete("/workflow/{wf_id}",   workflow_delete_handler)
    # 知识库
    app.router.add_get("/kb/docs",              kb_docs_handler)
    app.router.add_post("/kb/search",           kb_search_handler)
    app.router.add_post("/kb/upload",           kb_upload_handler)
    app.router.add_delete("/kb/docs/{doc_id}",  kb_delete_handler)
    app.router.add_options("/kb/{tail:.*}",     kb_options_handler)
    # TTS
    app.router.add_post("/tts",                    tts_handler)
    app.router.add_get("/tts/voices",              tts_voices_handler)
    # Agent 配置（名称 / 音色）
    app.router.add_get("/config/agents",           agent_config_get)
    app.router.add_post("/config/agents",          agent_config_set)
    # Onboarding / FTUE
    app.router.add_get("/setup/status",            setup_status_handler)
    app.router.add_post("/setup/save",             setup_save_handler)
    app.router.add_get("/setup/welcome",           setup_welcome_handler)
    app.router.add_post("/setup/complete",         setup_complete_handler)
    # Skills
    app.router.add_get("/skills",                          skills_list_handler)
    app.router.add_get("/skills/{skill_id}",               skill_get_handler)
    app.router.add_post("/skills/{skill_id}/usage",        skill_record_usage_handler)
    app.router.add_post("/skills/{skill_id}/upgrade",      skill_upgrade_handler)
    app.router.add_post("/skills/install",                 skill_install_handler)
    # Membership (会员)
    app.router.add_get("/membership/status",               membership_status_handler)
    app.router.add_post("/membership/activate",            membership_activate_handler)
    app.router.add_post("/membership/deactivate",          membership_deactivate_handler)
    # Reports (日报 / 周报)
    app.router.add_get("/reports/status",                  report_status_handler)
    app.router.add_get("/reports/daily",                   report_daily_handler)
    app.router.add_get("/reports/weekly",                  report_weekly_handler)
    # Vault (Obsidian)
    app.router.add_get("/vault/tree",                      vault_tree_handler)
    app.router.add_get("/vault/file",                      vault_read_handler)
    app.router.add_post("/vault/file",                     vault_write_handler)
    app.router.add_post("/shoucang/sop",                    shoucang_sop_handler)
    # Memory 统一接口（SQLite / Obsidian 双后端）
    app.router.add_post("/memory/learn",                   memory_learn_handler)
    app.router.add_get("/memory/backend",                  memory_backend_get)
    app.router.add_post("/memory/backend",                 memory_backend_set)
    app.router.add_post("/memory/migrate",                 memory_migrate_handler)
    app.router.add_get("/memory/entries",                  memory_list_handler)
    app.router.add_get("/memory/search",                   memory_search_handler)
    app.router.add_delete("/memory/entries/{id}",          memory_delete_handler)
    # Project context management (Phase 3)
    # 注意：固定路径 /projects/deactivate 必须在参数路径 /projects/{name}/activate 之前注册
    # 否则 aiohttp 会将 "deactivate" 匹配为 {name}
    app.router.add_get("/projects",                        projects_list_handler)
    app.router.add_post("/projects",                       project_create_handler)
    app.router.add_post("/projects/deactivate",            project_deactivate_handler)
    app.router.add_post("/projects/{name}/activate",       project_activate_handler)
    # Webhook trigger (Phase 3 — CI/CD / Zapier / n8n)
    app.router.add_post("/hook/{agent_id}",                webhook_trigger_handler)
    # OpenAPI docs (Phase 4)
    from openapi_spec import get_spec_json, SWAGGER_UI_HTML
    async def _openapi_json(req):
        return web.Response(text=get_spec_json(),
                            content_type="application/json", headers=CORS_HEADERS)
    async def _swagger_ui(req):
        return web.Response(text=SWAGGER_UI_HTML, content_type="text/html")
    app.router.add_get("/openapi.json", _openapi_json)
    app.router.add_get("/docs",         _swagger_ui)
    # API config (丰富化)
    app.router.add_get("/config/api-catalog",              api_catalog_handler)
    app.router.add_post("/config/api-save",                api_save_handler)
    app.router.add_post("/config/api-test/{api_id}",       api_test_handler)
    # CORS preflight for all config routes
    async def _options(req): return web.Response(headers=CORS_HEADERS)
    app.router.add_options("/{tail:.*}", _options)

    # 启动定时任务调度器
    async def _run_agent(agent_id: str, prompt: str) -> str:
        srv = servers.get(agent_id)
        if not srv:
            return f"错误：未知 agent {agent_id}"
        return await srv.worker.run(prompt)

    _scheduler.set_run_fn(_run_agent)
    _scheduler.start()
    _watcher.set_run_fn(_run_agent)
    _watcher.start()

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT_WS)
    await site.start()

    print("=" * 52)
    print("  Anima — 后端服务 v1.0.0")
    print("=" * 52)
    print(f"  健康检查:  http://127.0.0.1:{PORT_WS}/health")
    print(f"  陶朱控制台: http://127.0.0.1:{PORT_WS}/console")
    print(f"  用量统计:  http://127.0.0.1:{PORT_WS}/usage")
    print(f"  Anima: ws://127.0.0.1:{PORT_WS}/ws/xi")
    print(f"  晞:    ws://127.0.0.1:{PORT_WS}/ws/yiyi")
    print(f"  陶朱:  ws://127.0.0.1:{PORT_WS}/ws/tianyuan")
    print(f"  执行者:   ws://127.0.0.1:{PORT_WS}/ws/executor")
    print(f"  写手:     ws://127.0.0.1:{PORT_WS}/ws/writer")
    print(f"  阅读者:   ws://127.0.0.1:{PORT_WS}/ws/reader")
    print(f"  评审:     ws://127.0.0.1:{PORT_WS}/ws/critic")
    print("=" * 52)

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()
        search_engine.close()
        print("\n已停止。")


if __name__ == "__main__":
    asyncio.run(main())
