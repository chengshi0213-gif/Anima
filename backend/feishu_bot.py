#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
feishu_bot.py — 飞书双向机器人（长连接，免公网 URL）

让用户把自己的飞书自建应用接进 Anima：在飞书里 @ 机器人或私聊，
对应人格就会回复。走飞书开放平台的「长连接」事件订阅（WebSocket），
所以 Anima 跑在本机 localhost 也能收消息，无需公网回调地址。

用户只需在飞书开放平台建一个自建应用 → 开启机器人能力 → 订阅
「接收消息 im.message.receive_v1」事件（连接方式选「长连接」）→
把 App ID / App Secret 填进 Anima 设置页即可。凭证只存在本机
~/.anima/data/feishu.json，绝不外传。

线程模型：lark 的 ws.Client.start() 是阻塞的（自带事件循环），
放到独立 daemon 线程跑；收到消息时用 run_coroutine_threadsafe
把任务桥回主 aiohttp 事件循环上的 _run_agent，拿到回复再用
lark 同步客户端发回飞书。
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import deque
from pathlib import Path
from typing import Awaitable, Callable, Optional

from config import DATA_DIR

log = logging.getLogger("feishu_bot")

_CFG_PATH = DATA_DIR / "feishu.json"
VALID_AGENTS = {"xi", "yiyi", "tianyuan", "shoucang"}
_REPLY_TIMEOUT = 240          # 单条消息等待人格回复的上限（秒）
_DEDUP_MAX = 512              # 去重缓存的 message_id 数量上限


# ── 配置读写 ────────────────────────────────────────────
def _default_cfg() -> dict:
    return {
        "app_id": "",
        "app_secret": "",
        "default_agent": "xi",   # 默认由哪个人格回复
        "enabled": False,        # 是否随后端自动启动
        "strip_at": True,        # 群里 @机器人 时去掉 @ 前缀再喂给人格
        "reply_in_thread": False,
    }


def load_config() -> dict:
    cfg = _default_cfg()
    if _CFG_PATH.exists():
        try:
            cfg.update(json.loads(_CFG_PATH.read_text("utf-8")) or {})
        except Exception as e:
            log.warning("读取飞书配置失败: %s", e)
    return cfg


def save_config(patch: dict) -> dict:
    """合并保存。app_secret 传空字符串表示「不修改」，避免前端回显时清空。"""
    cfg = load_config()
    for k, v in (patch or {}).items():
        if k == "app_secret" and v in (None, "", "********"):
            continue  # 保留原密钥
        if k == "default_agent" and v not in VALID_AGENTS:
            continue
        if k in _default_cfg():
            cfg[k] = v
    _CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    return cfg


def config_public() -> dict:
    """给前端看的安全版：不回传明文密钥，只标记是否已配置。"""
    cfg = load_config()
    return {
        "app_id": cfg.get("app_id", ""),
        "has_secret": bool(cfg.get("app_secret")),
        "default_agent": cfg.get("default_agent", "xi"),
        "enabled": cfg.get("enabled", False),
        "strip_at": cfg.get("strip_at", True),
        "reply_in_thread": cfg.get("reply_in_thread", False),
    }


# ── 凭证校验（不连长连接，只换一次 token）────────────────
def verify_credentials(app_id: str, app_secret: str) -> dict:
    """用 app_id/secret 换一次 tenant_access_token，验证凭证是否有效。"""
    if not app_id or not app_secret:
        return {"ok": False, "error": "App ID / App Secret 不能为空"}
    try:
        import lark_oapi as lark
        cli = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
        # 内部会缓存并请求 tenant_access_token；用一个轻量自查接口验证
        from lark_oapi.api.auth.v3 import (
            InternalTenantAccessTokenRequest,
            InternalTenantAccessTokenRequestBody,
        )
        req = (InternalTenantAccessTokenRequest.builder()
               .request_body(InternalTenantAccessTokenRequestBody.builder()
                             .app_id(app_id).app_secret(app_secret).build())
               .build())
        resp = cli.auth.v3.tenant_access_token.internal(req)
        if not resp.success() and resp.code not in (0, None):
            return {"ok": False, "error": f"飞书返回 code={resp.code} {resp.msg}"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 机器人主体 ──────────────────────────────────────────
class FeishuBot:
    """单实例：管理长连接生命周期 + 消息桥接。"""

    def __init__(self):
        self._run_fn: Optional[Callable[[str, str], Awaitable[str]]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ws = None
        self._lark = None
        self._running = False
        self._last_error: Optional[str] = None
        self._seen: deque[str] = deque(maxlen=_DEDUP_MAX)
        self._seen_set: set[str] = set()
        self._lock = threading.Lock()

    # 由 websocket_server.main() 注入：人格调用入口 + 主事件循环
    def configure(self, run_fn, loop):
        self._run_fn = run_fn
        self._loop = loop

    def status(self) -> dict:
        cfg = load_config()
        return {
            "running": self._running,
            "enabled": cfg.get("enabled", False),
            "configured": bool(cfg.get("app_id") and cfg.get("app_secret")),
            "default_agent": cfg.get("default_agent", "xi"),
            "error": self._last_error,
        }

    # ── 启停 ──
    def start(self) -> dict:
        with self._lock:
            if self._running:
                return {"ok": True, "msg": "已在运行"}
            cfg = load_config()
            app_id, app_secret = cfg.get("app_id"), cfg.get("app_secret")
            if not app_id or not app_secret:
                self._last_error = "未配置 App ID / App Secret"
                return {"ok": False, "error": self._last_error}
            if self._run_fn is None or self._loop is None:
                self._last_error = "机器人未接线（run_fn/loop 缺失）"
                return {"ok": False, "error": self._last_error}
            try:
                self._build_clients(app_id, app_secret)
            except Exception as e:
                self._last_error = f"初始化失败: {e}"
                log.exception("飞书机器人初始化失败")
                return {"ok": False, "error": self._last_error}
            self._last_error = None
            self._thread = threading.Thread(
                target=self._run_ws, name="feishu-ws", daemon=True)
            self._thread.start()
            self._running = True
            log.info("飞书机器人已启动（长连接）")
            return {"ok": True}

    def stop(self) -> dict:
        with self._lock:
            self._running = False
            try:
                if self._ws is not None:
                    # ws.Client 没有公开 stop；断开底层连接让 start() 线程退出
                    disc = getattr(self._ws, "_disconnect", None)
                    if disc:
                        try:
                            disc()
                        except Exception:
                            pass
            finally:
                self._ws = None
            log.info("飞书机器人已停止")
            return {"ok": True}

    # ── 内部 ──
    def _build_clients(self, app_id: str, app_secret: str):
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

        # 同步客户端：用于回复消息
        self._lark = (lark.Client.builder()
                      .app_id(app_id).app_secret(app_secret).build())

        handler = (lark.EventDispatcherHandler.builder("", "")
                   .register_p2_im_message_receive_v1(self._on_message)
                   .build())
        self._ws = lark.ws.Client(
            app_id, app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.WARNING,
        )

    def _run_ws(self):
        try:
            self._ws.start()  # 阻塞，直到断开
        except Exception as e:
            self._last_error = str(e)
            log.warning("飞书长连接退出: %s", e)
        finally:
            self._running = False

    def _dedup(self, message_id: str) -> bool:
        """True 表示重复（已处理过）。飞书可能重复投递，需幂等。"""
        if not message_id:
            return False
        if message_id in self._seen_set:
            return True
        if len(self._seen) >= self._seen.maxlen:
            old = self._seen.popleft()
            self._seen_set.discard(old)
        self._seen.append(message_id)
        self._seen_set.add(message_id)
        return False

    def _on_message(self, data):
        """长连接线程里被回调（同步）。解析→桥到主循环→回复。"""
        try:
            msg = data.event.message
            message_id = getattr(msg, "message_id", None)
            if self._dedup(message_id):
                return
            if getattr(msg, "message_type", None) != "text":
                self._reply(message_id, "我现在只看得懂文字消息～")
                return
            content = json.loads(msg.content or "{}")
            text = (content.get("text") or "").strip()
            cfg = load_config()
            if cfg.get("strip_at", True):
                # 去掉 @_user_1 这类 @ 占位
                import re
                text = re.sub(r"@_user_\d+", "", text).strip()
            if not text:
                return
            agent = cfg.get("default_agent", "xi")
            reply = self._invoke_agent(agent, text)
            self._reply(message_id, reply or "（没有内容）")
        except Exception as e:
            log.exception("处理飞书消息失败: %s", e)

    def _invoke_agent(self, agent: str, text: str) -> str:
        if self._run_fn is None or self._loop is None:
            return "机器人未正确接线。"
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._run_fn(agent, text), self._loop)
            return fut.result(timeout=_REPLY_TIMEOUT)
        except Exception as e:
            log.warning("调用人格失败: %s", e)
            return f"处理时出错了：{e}"

    def _reply(self, message_id: str, text: str):
        if not self._lark or not message_id:
            return
        try:
            from lark_oapi.api.im.v1 import (
                ReplyMessageRequest, ReplyMessageRequestBody)
            cfg = load_config()
            body = (ReplyMessageRequestBody.builder()
                    .content(json.dumps({"text": text}, ensure_ascii=False))
                    .msg_type("text")
                    .reply_in_thread(bool(cfg.get("reply_in_thread", False)))
                    .build())
            req = (ReplyMessageRequest.builder()
                   .message_id(message_id).request_body(body).build())
            resp = self._lark.im.v1.message.reply(req)
            if not resp.success():
                log.warning("飞书回复失败 code=%s msg=%s", resp.code, resp.msg)
        except Exception as e:
            log.warning("飞书回复异常: %s", e)


# 进程级单例
bot = FeishuBot()
