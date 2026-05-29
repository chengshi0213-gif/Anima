"""
ws_manager.py — WorkerServer: 每个 Agent 的 WebSocket 连接管理器
处理 chat / status / search / workflow / usage / cancel 等 WS action
"""
import json
import asyncio
import aiohttp
from aiohttp import web

from agent_base import PermissionRequest


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
            await ws.send_json({"type": "error", "message": "消息为空"})
            return

        selected_model = data.get("model") or None
        session_id = data.get("session_id") or f"{self.worker.name}-{int(asyncio.get_event_loop().time())}"
        self.current_session_id = session_id
        await ws.send_json({"type": "status", "status": "running",
                            "session_id": session_id, "model": selected_model})

        # ── 以后台 task 运行，不阻塞消息循环 ──
        #   关键：handle() 的 `async for msg ... await handler` 是顺序执行的，
        #   若在此处 await worker.run() 会卡住整个循环，导致后续的 cancel 消息
        #   永远读不到。包成 task 并记录 current_task，cancel 才能真正生效。
        async def _run_and_respond():
            try:
                result = await self.worker.run(
                    message, session_id=session_id, model=selected_model, ws=ws)
            except asyncio.CancelledError:
                await self._safe_send(ws, {"type": "response", "data": {
                    "session_id": session_id, "status": "cancelled",
                    "summary": "已取消", "turn_count": 0,
                }})
                raise
            except PermissionRequest as pr:
                await self._safe_send(ws, {
                    "type": "permission_request",
                    "data": {
                        "api_name":     pr.api_name,
                        "reason":       pr.reason,
                        "signup_url":   pr.signup_url,
                        "alternatives": pr.alternatives,
                        "related":      pr.related,
                    }
                })
                return
            except Exception as e:
                await self._safe_send(ws, {"type": "error", "message": str(e)})
                return
            self.search.index_session(session_id, self.worker.name, [
                {"role": "user", "content": message},
                {"role": "assistant", "content": result.get("summary", "")},
            ])
            await self._safe_send(ws, {"type": "response", "data": {
                "session_id":    session_id,
                "status":        result["status"],
                "summary":       result.get("summary", ""),
                "model":         selected_model or self.worker.model,
                "files_changed": result.get("files_changed", []),
                "turn_count":    result.get("turn_count", 0),
            }})

        self.current_task = asyncio.create_task(_run_and_respond())

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
