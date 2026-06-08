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
from routes import core, knowledge, workflow, config as config_routes, services, data, login, economy, invite, tasks


async def main():
    # 一次性把 config.yaml 残留的明文 API Key 迁移为加密存储（幂等）
    try:
        import config as _cfg_mod
        await asyncio.to_thread(_cfg_mod.migrate_encrypt_secrets)
    except Exception as _e:
        print(f"[Anima] 密钥加密迁移跳过: {_e}")

    # asyncio 事件循环未捕获异常 → 落盘崩溃报告
    try:
        import crash_reporter as _cr
        _loop = asyncio.get_running_loop()

        def _aio_exc_handler(loop, context):
            exc = context.get("exception")
            msg = context.get("message", "asyncio error")
            try:
                if exc is not None:
                    _cr.dump_exception(type(exc), exc, exc.__traceback__, context=msg)
                else:
                    _cr.dump_message(msg, context="asyncio")
            except Exception:
                pass
            loop.default_exception_handler(context)

        _loop.set_exception_handler(_aio_exc_handler)
    except Exception as _e:
        print(f"[Anima] asyncio 异常钩子安装失败: {_e}")

    # 初始化内置 Skill
    await asyncio.to_thread(init_builtin_skills)

    # 启动 MCP 客户端（M11）：在主循环上连接 config 里 enabled 的 server。
    # 容错：未装 SDK / 未配置 / 单个 server 失败均不影响主程序启动；默认无 server=空连接。
    try:
        from mcp_client import MCPManager
        await MCPManager.boot(asyncio.get_running_loop())
    except Exception as _e:
        print(f"[Anima] MCP 启动跳过: {_e}")

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
    app["usage_tracker"] = usage_tracker

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
    economy.register(app)
    invite.register(app)
    login.register(app)
    tasks.register(app)

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

    # ── 飞书双向机器人：接线主循环 + 人格入口，按配置自动启动 ──
    try:
        import feishu_bot
        feishu_bot.bot.configure(_run_agent, asyncio.get_running_loop())
        if feishu_bot.load_config().get("enabled"):
            res = feishu_bot.bot.start()
            print(f"  飞书机器人: {'已启动' if res.get('ok') else '启动失败 ' + str(res.get('error'))}")
    except Exception as _e:
        print(f"  飞书机器人接线失败: {_e}")

    # ── 企业微信 / 公众号：回调模式，接线人格入口（端点常驻，按需启用）──
    try:
        import wechat_bot
        wechat_bot.bot.configure(_run_agent, asyncio.get_running_loop())
        if wechat_bot.load_config().get("enabled"):
            print("  企业微信/公众号: 已启用（回调端点 /integrations/wechat/callback）")
    except Exception as _e:
        print(f"  微信机器人接线失败: {_e}")

    # ── 邮箱管家：IMAP 收申请 → 自动发结缘码（仅总代理实例启用）──
    try:
        import invite_mailer
        invite_mailer.mailer.configure(asyncio.get_running_loop())
        if invite_mailer.load_config().get("enabled"):
            res = invite_mailer.mailer.start()
            print(f"  邮箱管家: {'已启动' if res.get('ok') else '未启动 ' + str(res.get('error'))}")
    except Exception as _e:
        print(f"  邮箱管家接线失败: {_e}")

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
    # dev 模式直跑：也初始化中央日志（幂等）
    try:
        from log_config import setup_logging
        setup_logging()
    except Exception as _e:
        print(f"[Anima] 日志初始化失败（降级为 print）: {_e}")
    asyncio.run(main())
