"""
ws_manager.py — WorkerServer: 每个 Agent 的 WebSocket 连接管理器
处理 chat / status / search / workflow / usage / cancel 等 WS action
"""
import json
import asyncio
import aiohttp
from aiohttp import web

from agent_base import PermissionRequest
from task_registry import get_registry


class WorkerServer:
    def __init__(self, worker, search_engine, workflow_mgr, usage_tracker):
        self.worker = worker
        self.search = search_engine
        self.workflow = workflow_mgr
        self.usage = usage_tracker
        self.tasks = get_registry()          # M12：共享任务注册表（提交走人 + 重连看流）
        self.current_task = None             # 向后兼容：最近一个 asyncio.Task（cancel/status 用）
        self.current_session_id = None
        # 每个会话的完整对话累积（session_id -> [ {role,content}, ... ]）。
        # 关键：index_session 是"删旧重写"语义，必须每轮传**整段**对话，
        # 否则多轮会话只会保留最后一轮 → 历史记录形同虚设。
        self._session_msgs: dict[str, list] = {}

    def _record_turn(self, session_id: str, user_msg: str, assistant_summary: str):
        """把这一轮 user/assistant 追加进该会话的完整对话，并整段重新索引。
        续接旧会话（进程重启后）时先从 DB 捞回已存消息，避免覆盖历史。"""
        hist = self._session_msgs.get(session_id)
        if hist is None:
            try:
                hist = self.search.get_session_messages(session_id) or []
            except Exception:
                hist = []
            self._session_msgs[session_id] = hist
        hist.append({"role": "user", "content": user_msg})
        hist.append({"role": "assistant", "content": assistant_summary})
        self.search.index_session(session_id, self.worker.name, hist)
        return hist

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
                    # ── M12 内核2：异步任务（提交走人 / 断线重连）──
                    "task_submit":       self._handle_task_submit,
                    "task_attach":       self._handle_task_attach,
                    "task_list":         self._handle_task_list,
                    "task_cancel":       self._handle_task_cancel,
                    # ── M14 内核3：危险操作确认答复 ──
                    "confirm_response":  self._handle_confirm_response,
                    # ── C1 v1.2.2：用户回答 ask_user ──
                    "user_answer":       self._handle_user_answer,
                }
                handler = handlers.get(action)
                if handler:
                    await handler(ws, data)
                else:
                    await ws.send_json({"type": "error", "message": f"未知 action: {action}"})
            except Exception as e:
                await ws.send_json({"type": "error", "message": str(e)})
        # 连接关闭：把所有 attach 到本 ws 的 live 任务解绑，避免向死连接发送。
        # 任务本身继续在后台跑（提交走人）；重连后用 task_attach 拉回流。
        self.tasks.detach_ws(ws)
        return ws

    def _prepare_chat(self, data):
        """从 chat / task_submit 请求体提炼 (message, model, session_id, error)。
        附件拼接逻辑两个入口共用。"""
        message = data.get("message", "")
        files   = data.get("files", [])
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
            return "", None, "", "消息为空"
        model = data.get("model") or None
        session_id = data.get("session_id") or f"{self.worker.name}-{int(asyncio.get_event_loop().time())}"
        return message, model, session_id, ""

    def _spawn_task(self, task, selected_model, plan_mode=False):
        """把任务跑成主循环上的 asyncio.Task：不阻塞消息循环，可 cancel / 重连。
        task 自身当作 ws 传给 worker.run（缓冲事件 + 转发给当前 attach 的 ws），
        这样断线重连 task_attach 即可换上新 ws 并 replay，流不丢。"""
        async def _run():
            self.tasks.set_status(task, "running")
            try:
                run_kwargs = dict(session_id=task.session_id,
                                  model=selected_model, ws=task)
                if plan_mode:
                    run_kwargs["plan_mode"] = True
                result = await self.worker.run(task.message, **run_kwargs)
            except asyncio.CancelledError:
                self.tasks.set_status(task, "cancelled", "已取消")
                await task.send_json({"type": "response", "data": {
                    "session_id": task.session_id, "task_id": task.task_id,
                    "status": "cancelled", "summary": "已取消", "turn_count": 0,
                }})
                raise
            except PermissionRequest as pr:
                self.tasks.set_status(task, "error", "需要权限")
                await task.send_json({"type": "permission_request", "data": {
                    "api_name":     pr.api_name,
                    "reason":       pr.reason,
                    "signup_url":   pr.signup_url,
                    "alternatives": pr.alternatives,
                    "related":      pr.related,
                }})
                return
            except Exception as e:
                self.tasks.set_status(task, "error", str(e))
                await task.send_json({"type": "error", "message": str(e)})
                return
            task.result = result
            self.tasks.set_status(task, "done", result.get("summary", ""))
            self._record_turn(task.session_id, task.message, result.get("summary", ""))
            await task.send_json({"type": "response", "data": {
                "session_id":    task.session_id,
                "task_id":       task.task_id,
                "status":        result["status"],
                "summary":       result.get("summary", ""),
                "model":         selected_model or self.worker.model,
                "files_changed": result.get("files_changed", []),
                "turn_count":    result.get("turn_count", 0),
            }})

        task.aio_task = asyncio.create_task(_run())
        self.current_task = task.aio_task   # 向后兼容：cancel / status 仍指最近任务

    async def _handle_chat(self, ws, data):
        """老入口：chat = submit + 自动 attach。行为与旧版一致，老前端零改动。"""
        message, selected_model, session_id, err = self._prepare_chat(data)
        if err:
            await ws.send_json({"type": "error", "message": err})
            return
        self.current_session_id = session_id
        plan_mode = bool(data.get("plan_mode", False))
        task = self.tasks.create(self.worker.name, session_id, message)
        self.tasks.attach(task.task_id, ws)
        await ws.send_json({"type": "status", "status": "running",
                            "session_id": session_id, "task_id": task.task_id,
                            "model": selected_model})
        self._spawn_task(task, selected_model, plan_mode=plan_mode)

    @staticmethod
    async def _safe_send(ws, payload):
        """安全发送 WS 消息，忽略连接已关闭等错误。"""
        try:
            await ws.send_json(payload)
        except Exception:
            pass

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

    # ── M12 内核2：异步任务 actions ──
    async def _handle_task_submit(self, ws, data):
        """提交即走人：建任务 + 立即回 task_id（也顺手 attach，留下就能看流）。"""
        message, model, session_id, err = self._prepare_chat(data)
        if err:
            await ws.send_json({"type": "error", "message": err})
            return
        self.current_session_id = session_id
        task = self.tasks.create(self.worker.name, session_id, message)
        self.tasks.attach(task.task_id, ws)
        await ws.send_json({"type": "task_submitted", "data": {
            "task_id": task.task_id, "session_id": session_id}})
        self._spawn_task(task, model)

    async def _handle_task_attach(self, ws, data):
        """断线重连：换上新 ws + replay 缓冲事件。任务已结束则回历史记录。"""
        task_id = data.get("task_id", "")
        task = self.tasks.attach(task_id, ws)
        if task is None:
            rec = self.tasks.get_record(task_id)
            if rec is None:
                await ws.send_json({"type": "error", "message": f"任务不存在: {task_id}"})
                return
            await ws.send_json({"type": "task_state", "data": rec})
            return
        await ws.send_json({"type": "task_state", "data": task.to_dict()})
        await self.tasks.replay(task_id, ws)

    async def _handle_task_list(self, ws, data=None):
        tasks = self.tasks.list(agent=self.worker.name)
        await ws.send_json({"type": "response", "data": {"tasks": tasks}})

    async def _handle_task_cancel(self, ws, data):
        task_id = data.get("task_id", "")
        ok = await self.tasks.cancel(task_id)
        await ws.send_json({"type": "response", "data": {
            "cancelled": ok, "task_id": task_id}})

    async def _handle_confirm_response(self, ws, data):
        """用户对 confirm_request 的答复：approved + scope(once/session/always)。"""
        from confirm import get_broker
        ok = get_broker().resolve(
            data.get("confirm_id", ""),
            bool(data.get("approved", False)),
            data.get("scope", "once"))
        await ws.send_json({"type": "response", "data": {"resolved": ok}})

    async def _handle_user_answer(self, ws, data):
        """C1: 用户回答 ask_user 提问——set event 恢复 agent 协程。"""
        answer = data.get("answer", "")
        if hasattr(self.worker, "receive_user_answer"):
            self.worker.receive_user_answer(answer)
        await ws.send_json({"type": "response", "data": {"received": True}})
