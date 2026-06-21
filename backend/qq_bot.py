#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qq_bot.py — QQ 机器人接入（OneBot v11 反向 WebSocket）

原理：
  Anima 在 /integrations/qq/ws 开一个 WebSocket 端点（Anima 是服务端）。
  NapCat / LLOneBot 配置「反向 WebSocket」连接到该端点，
  QQ 消息经由 NapCat → Anima 人格 → 回复 → 用户。

优势：
  · 全程在本机，无需公网 URL、无需内网穿透
  · 用现有 QQ 账号即可，无需申请机器人资质

NapCat 配置（Windows 版）：
  1. 下载 NapCatQQ.exe，登录你的 QQ 账号
  2. 打开 NapCat 控制台 → 网络配置 → 添加反向 WebSocket 客户端
  3. 填入 URL: ws://127.0.0.1:9100/integrations/qq/ws
  4. 保存，NapCat 连上后状态变为「已连接」

凭证存 ~/.anima/data/qq_bot.json
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import deque
from pathlib import Path
from typing import Awaitable, Callable, Optional, Any

from config import DATA_DIR

log = logging.getLogger("qq_bot")

_CFG_PATH = DATA_DIR / "qq_bot.json"
VALID_AGENTS = {"xi", "yiyi", "tianyuan", "shoucang"}
_DEDUP_MAX = 512


# ── 配置 ──────────────────────────────────────────────
def _default_cfg() -> dict:
    return {
        "enabled": False,
        "default_agent": "xi",
        "respond_without_at": False,   # 群里不@也回
        "allow_private": True,          # 响应私聊
        "allow_group": True,            # 响应群聊
    }


def load_config() -> dict:
    cfg = _default_cfg()
    if _CFG_PATH.exists():
        try:
            cfg.update(json.loads(_CFG_PATH.read_text("utf-8")) or {})
        except Exception as e:
            log.warning("读取 QQ 配置失败: %s", e)
    return cfg


def save_config(patch: dict) -> dict:
    cfg = load_config()
    for k, v in (patch or {}).items():
        if k == "default_agent" and v not in VALID_AGENTS:
            continue
        if k in _default_cfg():
            cfg[k] = v
    _CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    return cfg


def config_public() -> dict:
    cfg = load_config()
    return {
        "enabled": cfg.get("enabled", False),
        "default_agent": cfg.get("default_agent", "xi"),
        "respond_without_at": cfg.get("respond_without_at", False),
        "allow_private": cfg.get("allow_private", True),
        "allow_group": cfg.get("allow_group", True),
    }


# ── 文本提取（兼容 OneBot v11 字符串/数组两种格式）──
def _extract_text(message: Any) -> str:
    if isinstance(message, str):
        # CQ 码格式，去掉 at、图片等非文字段
        import re
        clean = re.sub(r"\[CQ:[^\]]+\]", "", message)
        return clean.strip()
    if isinstance(message, list):
        return " ".join(
            seg.get("data", {}).get("text", "")
            for seg in message
            if seg.get("type") == "text"
        ).strip()
    return ""


def _has_at(message: Any, self_id: Any) -> bool:
    """判断消息里是否 @ 了机器人自己。"""
    if isinstance(message, list):
        for seg in message:
            if seg.get("type") == "at":
                qq = str(seg.get("data", {}).get("qq", ""))
                if qq == str(self_id) or qq == "all":
                    return True
    if isinstance(message, str):
        import re
        return bool(re.search(rf"\[CQ:at,qq={self_id}\]", message))
    return False


# ── 机器人核心 ─────────────────────────────────────────
class QQBot:
    """单实例——持有当前 OneBot WebSocket 连接 + 消息派发。"""

    def __init__(self):
        self._ws = None                     # aiohttp WebSocketResponse
        self._run_fn: Optional[Callable[[str, str], Awaitable[str]]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._seen: deque[str] = deque(maxlen=_DEDUP_MAX)
        self._seen_set: set[str] = set()
        self._lock = threading.Lock()
        self._connected = False
        self._last_error: Optional[str] = None
        self._peer: Optional[str] = None   # 当前连接的 NapCat 地址

    def configure(self, run_fn, loop):
        """由 websocket_server.main() 注入人格调用函数 + 主事件循环。"""
        self._run_fn = run_fn
        self._loop = loop

    def status(self) -> dict:
        cfg = load_config()
        return {
            "running": self._connected,
            "enabled": cfg.get("enabled", False),
            "connected": self._connected,
            "peer": self._peer,
            "default_agent": cfg.get("default_agent", "xi"),
            "error": self._last_error,
        }

    async def handle_connection(self, ws, peer: str = ""):
        """
        WebSocket 路由处理器把已 prepare 好的 ws 对象传入此方法，
        此方法阻塞直到连接断开。
        """
        if not load_config().get("enabled"):
            await ws.close(code=1008, message=b"QQ bot not enabled")
            return

        with self._lock:
            self._ws = ws
            self._connected = True
            self._peer = peer
            self._last_error = None

        log.info("QQ OneBot 已连接: %s", peer)

        try:
            import aiohttp
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        event = json.loads(msg.data)
                    except Exception:
                        continue
                    asyncio.ensure_future(self._handle_event(event))
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    break
        except Exception as e:
            self._last_error = str(e)
            log.warning("QQ OneBot 连接错误: %s", e)
        finally:
            with self._lock:
                self._ws = None
                self._connected = False
                self._peer = None
            log.info("QQ OneBot 连接已断开")

    async def _handle_event(self, event: dict):
        """处理单条 OneBot v11 事件。"""
        if event.get("post_type") != "message":
            return

        cfg = load_config()
        msg_type = event.get("message_type", "")  # private / group
        user_id = event.get("user_id")
        self_id = event.get("self_id")
        message = event.get("message", "")
        msg_id = str(event.get("message_id", ""))

        # 私聊/群聊过滤
        if msg_type == "private" and not cfg.get("allow_private", True):
            return
        if msg_type == "group" and not cfg.get("allow_group", True):
            return

        # 群聊：只响应 @ 机器人的消息（除非 respond_without_at）
        if msg_type == "group":
            if not cfg.get("respond_without_at") and not _has_at(message, self_id):
                return

        text = _extract_text(message)
        if not text:
            return

        # 去重
        if msg_id:
            if msg_id in self._seen_set:
                return
            self._seen.append(msg_id)
            self._seen_set.add(msg_id)
            if len(self._seen_set) > _DEDUP_MAX:
                old = self._seen.popleft()
                self._seen_set.discard(old)

        agent_id = cfg.get("default_agent", "xi")
        if self._run_fn is None:
            log.warning("QQ: run_fn 未注入，跳过消息")
            return

        try:
            reply = await self._run_fn(agent_id, text)
        except Exception as e:
            log.warning("QQ: agent 调用失败: %s", e)
            return

        if not reply or self._ws is None:
            return

        try:
            if msg_type == "private":
                payload = {
                    "action": "send_private_msg",
                    "params": {"user_id": user_id, "message": str(reply)},
                    "echo": msg_id,
                }
            else:
                group_id = event.get("group_id")
                payload = {
                    "action": "send_group_msg",
                    "params": {"group_id": group_id, "message": str(reply)},
                    "echo": msg_id,
                }
            await self._ws.send_str(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            log.warning("QQ: 发送回复失败: %s", e)


bot = QQBot()
