#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket 通信层 — Anima
Tauri 桌面壳 ↔ Python 后端的桥梁

入口文件：初始化 Worker、注册路由、启动服务
路由处理器已拆分到 routes/ 子包
"""
import sys, asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from aiohttp import web

from config import PORT_WS, LOG_DIR, SESSIONS_DB, WORKFLOWS_DIR
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
from scheduler import scheduler as _scheduler
from file_watcher import watcher as _watcher
from skill_manager import init_builtin_skills

from ws_manager import WorkerServer
from routes.auth import auth_middleware, CORS_HEADERS
from routes import core, knowledge, workflow, config as config_routes, services, data


async def main():
    # 初始化内置 Skill
    await asyncio.to_thread(init_builtin_skills)

    search_engine = SearchEngine(SESSIONS_DB)
    workflow_mgr  = WorkflowManager(WORKFLOWS_DIR)
    usage_tracker = UsageTracker(LOG_DIR)

    # 创建所有 Agent Worker
    servers = {
        "xi":       WorkerServer(XiWorker(),       search_engine, workflow_mgr, usage_tracker),
        "yiyi":     WorkerServer(YiyiWorker(),     search_engine, workflow_mgr, usage_tracker),
        "tianyuan": WorkerServer(TianyuanWorker(), search_engine, workflow_mgr, usage_tracker),
        "shoucang": WorkerServer(ShoucangWorker(), search_engine, workflow_mgr, usage_tracker),
        "executor": WorkerServer(ExecutorWorker(), search_engine, workflow_mgr, usage_tracker),
        "writer":   WorkerServer(WriterWorker(),   search_engine, workflow_mgr, usage_tracker),
        "reader":   WorkerServer(ReaderWorker(),   search_engine, workflow_mgr, usage_tracker),
        "critic":   WorkerServer(CriticWorker(),   search_engine, workflow_mgr, usage_tracker),
    }

    app = web.Application(middlewares=[auth_middleware])
    app["search_engine"] = search_engine
    app["servers"]       = servers
    app["workflow_mgr"]  = workflow_mgr

    # ── WebSocket 端点 ──
    for agent_id, srv in servers.items():
        app.router.add_get(f"/ws/{agent_id}", srv.handle)

    # ── HTTP 路由（各模块自注册）──
    core.register(app)
    knowledge.register(app)
    workflow.register(app)
    config_routes.register(app)
    services.register(app)
    data.register(app)

    # ── OpenAPI docs ──
    from openapi_spec import get_spec_json, SWAGGER_UI_HTML

    async def _openapi_json(req):
        return web.Response(text=get_spec_json(),
                            content_type="application/json", headers=CORS_HEADERS)

    async def _swagger_ui(req):
        return web.Response(text=SWAGGER_UI_HTML, content_type="text/html")

    app.router.add_get("/openapi.json", _openapi_json)
    app.router.add_get("/docs",         _swagger_ui)

    # ── CORS preflight ──
    async def _options(req):
        return web.Response(headers=CORS_HEADERS)

    app.router.add_options("/{tail:.*}", _options)

    # ── 启动调度器 & 文件监视器 ──
    async def _run_agent(agent_id: str, prompt: str) -> str:
        srv = servers.get(agent_id)
        if not srv:
            return f"错误：未知 agent {agent_id}"
        return await srv.worker.run(prompt)

    _scheduler.set_run_fn(_run_agent)
    _scheduler.start()
    _watcher.set_run_fn(_run_agent)
    _watcher.start()

    # ── 启动 HTTP 服务 ──
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
    for name in servers:
        print(f"  {name:10s} ws://127.0.0.1:{PORT_WS}/ws/{name}")
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
