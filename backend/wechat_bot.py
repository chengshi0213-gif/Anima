#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechat_bot.py — 企业微信 / 微信公众号 双向接入（回调模式 + 主动推送）

与飞书不同，企业微信和微信公众号都只支持「回调 URL」模式：腾讯服务器会
POST 到你提供的一个公网地址。Anima 跑在 localhost，所以需要一条内网穿透
隧道（cpolar / ngrok / frp 等）把本机端口暴露成公网 URL，填进微信后台。

回调有 5 秒响应限制，而人格回复要几十秒到几分钟——无法在回调里同步返回。
所以采用业界标准做法：
  1. 收到消息 → 立即回 "success" 给腾讯（避免它重试 + 给用户报错）
  2. 后台异步跑人格，拿到回复后用「主动推送 API」发回给用户
     - 企业微信：corpid + corpsecret 换 access_token → 应用消息 message/send
     - 公众号：  appid + appsecret 换 access_token → 客服消息 message/custom/send
       （客服消息需认证服务号；订阅号/未认证号此接口受限，会在状态里提示）

凭证只存本机 ~/.anima/data/wechat.json，绝不外传。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

import aiohttp

from config import DATA_DIR
import wechat_crypto as wxc

log = logging.getLogger("wechat_bot")

_CFG_PATH = DATA_DIR / "wechat.json"
VALID_AGENTS = {"xi", "yiyi", "tianyuan", "shoucang"}
VALID_PROVIDERS = {"wecom", "mp"}   # 企业微信 / 公众号
_DEDUP_MAX = 512
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}   # provider → (access_token, expire_ts)


# ── 配置 ─────────────────────────────────────────────────
def _default_cfg() -> dict:
    return {
        "provider": "wecom",      # wecom | mp
        "token": "",              # 回调 Token
        "aes_key": "",            # EncodingAESKey（43 位）
        # 企业微信
        "corp_id": "",
        "corp_secret": "",
        "agent_id": "",
        # 公众号
        "app_id": "",
        "app_secret": "",
        # 通用
        "default_agent": "xi",
        "enabled": False,
    }


def load_config() -> dict:
    cfg = _default_cfg()
    if _CFG_PATH.exists():
        try:
            cfg.update(json.loads(_CFG_PATH.read_text("utf-8")) or {})
        except Exception as e:
            log.warning("读取微信配置失败: %s", e)
    if cfg.get("provider") not in VALID_PROVIDERS:
        cfg["provider"] = "wecom"
    return cfg


_SECRET_KEYS = ("aes_key", "corp_secret", "app_secret")


def save_config(patch: dict) -> dict:
    cfg = load_config()
    for k, v in (patch or {}).items():
        if k in _SECRET_KEYS and v in (None, "", "********"):
            continue   # 留空 = 不修改已存密钥
        if k == "provider" and v not in VALID_PROVIDERS:
            continue
        if k == "default_agent" and v not in VALID_AGENTS:
            continue
        if k in _default_cfg():
            cfg[k] = v
    _CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    _TOKEN_CACHE.clear()   # 凭证可能变了，清缓存
    return cfg


def config_public() -> dict:
    cfg = load_config()
    rid = cfg.get("corp_id") if cfg.get("provider") == "wecom" else cfg.get("app_id")
    return {
        "provider": cfg.get("provider", "wecom"),
        "token": cfg.get("token", ""),
        "has_aes_key": bool(cfg.get("aes_key")),
        "corp_id": cfg.get("corp_id", ""),
        "has_corp_secret": bool(cfg.get("corp_secret")),
        "agent_id": cfg.get("agent_id", ""),
        "app_id": cfg.get("app_id", ""),
        "has_app_secret": bool(cfg.get("app_secret")),
        "default_agent": cfg.get("default_agent", "xi"),
        "enabled": cfg.get("enabled", False),
        "receiveid": rid or "",
    }


def _receiveid(cfg: dict) -> str:
    return cfg.get("corp_id", "") if cfg.get("provider") == "wecom" else cfg.get("app_id", "")


# ── 简易 XML 字段提取（只取需要的几个字段，避开 XML 解析攻击面）──
def _xml_field(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(?:<!\[CDATA\[(.*?)\]\]>|(.*?))</{tag}>", xml, re.DOTALL)
    if not m:
        return ""
    return (m.group(1) if m.group(1) is not None else m.group(2) or "").strip()


def _build_reply_xml(to_user: str, from_user: str, content: str) -> str:
    ts = int(time.time())
    return (f"<xml><ToUserName><![CDATA[{to_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
            f"<CreateTime>{ts}</CreateTime>"
            f"<MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{content}]]></Content></xml>")


# ── 机器人主体 ──────────────────────────────────────────
class WeChatBot:
    def __init__(self):
        self._run_fn: Optional[Callable[[str, str], Awaitable[str]]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._seen: list[str] = []
        self._seen_set: set[str] = set()
        self._last_error: Optional[str] = None

    def configure(self, run_fn, loop):
        self._run_fn = run_fn
        self._loop = loop

    def status(self) -> dict:
        cfg = load_config()
        prov = cfg.get("provider", "wecom")
        if prov == "wecom":
            configured = bool(cfg.get("token") and cfg.get("aes_key")
                              and cfg.get("corp_id") and cfg.get("corp_secret")
                              and cfg.get("agent_id"))
        else:
            configured = bool(cfg.get("token") and cfg.get("aes_key")
                              and cfg.get("app_id") and cfg.get("app_secret"))
        return {
            "provider": prov,
            "enabled": cfg.get("enabled", False),
            "configured": configured,
            "default_agent": cfg.get("default_agent", "xi"),
            "wired": self._run_fn is not None,
            "error": self._last_error,
        }

    def _dedup(self, msg_id: str) -> bool:
        if not msg_id:
            return False
        if msg_id in self._seen_set:
            return True
        self._seen.append(msg_id)
        self._seen_set.add(msg_id)
        if len(self._seen) > _DEDUP_MAX:
            old = self._seen.pop(0)
            self._seen_set.discard(old)
        return False

    # ── 回调：URL 验证（GET）──
    def verify_url(self, msg_signature: str, timestamp: str,
                   nonce: str, echostr: str) -> Optional[str]:
        cfg = load_config()
        token, aes = cfg.get("token", ""), cfg.get("aes_key", "")
        if not wxc.verify_signature(token, msg_signature, timestamp, nonce, echostr):
            return None
        try:
            return wxc.decrypt_msg(echostr, aes, _receiveid(cfg))
        except Exception as e:
            log.warning("URL 验证解密失败: %s", e)
            return None

    # ── 回调：收消息（POST）──
    async def handle_message(self, body: str, msg_signature: str,
                             timestamp: str, nonce: str) -> str:
        """返回给腾讯的响应体。立即回 'success'，人格回复走异步主动推送。"""
        cfg = load_config()
        if not cfg.get("enabled"):
            return "success"
        token, aes = cfg.get("token", ""), cfg.get("aes_key", "")
        encrypt = _xml_field(body, "Encrypt")
        if not encrypt:
            return "success"
        if not wxc.verify_signature(token, msg_signature, timestamp, nonce, encrypt):
            log.warning("微信消息签名校验失败")
            return "success"
        try:
            inner = wxc.decrypt_msg(encrypt, aes, _receiveid(cfg))
        except Exception as e:
            log.warning("微信消息解密失败: %s", e)
            return "success"

        msg_type = _xml_field(inner, "MsgType")
        if msg_type != "text":
            return "success"
        from_user = _xml_field(inner, "FromUserName")
        content = _xml_field(inner, "Content")
        msg_id = _xml_field(inner, "MsgId") or f"{from_user}:{_xml_field(inner,'CreateTime')}"
        if self._dedup(msg_id) or not content.strip():
            return "success"

        agent = cfg.get("default_agent", "xi")
        # 异步处理 + 主动推送，立即放行回调
        asyncio.create_task(self._process_and_push(cfg, agent, from_user, content.strip()))
        return "success"

    async def _process_and_push(self, cfg, agent, to_user, text):
        try:
            reply = await self._run_fn(agent, text) if self._run_fn else "机器人未接线。"
            if isinstance(reply, dict):
                reply = reply.get("summary") or reply.get("content") or str(reply)
            await self._push(cfg, to_user, reply or "（没有内容）")
        except Exception as e:
            log.warning("微信处理/推送失败: %s", e)
            try:
                await self._push(cfg, to_user, f"处理时出错了：{e}")
            except Exception:
                pass

    # ── access_token（带缓存）──
    async def _access_token(self, cfg) -> Optional[str]:
        prov = cfg.get("provider", "wecom")
        cached = _TOKEN_CACHE.get(prov)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
        try:
            async with aiohttp.ClientSession() as s:
                if prov == "wecom":
                    url = ("https://qyapi.weixin.qq.com/cgi-bin/gettoken"
                           f"?corpid={cfg.get('corp_id')}&corpsecret={cfg.get('corp_secret')}")
                else:
                    url = ("https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential"
                           f"&appid={cfg.get('app_id')}&secret={cfg.get('app_secret')}")
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    d = await r.json()
            tok = d.get("access_token")
            if not tok:
                self._last_error = f"换取 access_token 失败：{d}"
                return None
            _TOKEN_CACHE[prov] = (tok, time.time() + int(d.get("expires_in", 7200)))
            return tok
        except Exception as e:
            self._last_error = f"access_token 异常：{e}"
            return None

    async def _push(self, cfg, to_user, text):
        tok = await self._access_token(cfg)
        if not tok:
            return
        prov = cfg.get("provider", "wecom")
        async with aiohttp.ClientSession() as s:
            if prov == "wecom":
                url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={tok}"
                payload = {"touser": to_user, "msgtype": "text",
                           "agentid": int(cfg.get("agent_id") or 0),
                           "text": {"content": text}}
            else:
                url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={tok}"
                payload = {"touser": to_user, "msgtype": "text",
                           "text": {"content": text}}
            async with s.post(url, json=payload,
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                d = await r.json()
        if d.get("errcode") not in (0, None):
            self._last_error = f"推送失败 errcode={d.get('errcode')} {d.get('errmsg')}"
            log.warning(self._last_error)


# 进程级单例
bot = WeChatBot()
