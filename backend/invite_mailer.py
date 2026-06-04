#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
invite_mailer.py — 邮箱管家（自动发放结缘码）

只在「总代理」（你的 Anima 实例）上启用：
  IMAP 轮询邮箱 → 发现新的「申请引荐」邮件 → 自动铸造一枚邀请码 →
  SMTP 回信把码发给申请人 → 标记邮件已读。

凭证只存本机 ~/.anima/data/invite_mailer.json，绝不外传。
IMAP / SMTP 都是阻塞库，统一用 asyncio.to_thread 跑，避免卡事件循环。

线程/循环模型：后台 asyncio 任务循环，每 poll_interval_min 分钟跑一次
_poll_once()，内部把阻塞的 imap/smtp 调用丢进线程池。
"""
from __future__ import annotations

import asyncio
import json
import logging
import email
import imaplib
import smtplib
import re
from email.header import decode_header, make_header
from email.mime.text import MIMEText
from email.utils import parseaddr, formataddr
from pathlib import Path
from datetime import datetime, timezone

from config import DATA_DIR
import invite as _invite

log = logging.getLogger("invite_mailer")

_CFG_PATH = DATA_DIR / "invite_mailer.json"

# 已处理过的申请人邮箱（防止重复发码），持久化
_SENT_PATH = DATA_DIR / "invite_mailer_sent.json"


def _default_cfg() -> dict:
    return {
        "enabled": False,
        "imap_host": "",          # 如 imap.qq.com / imap.gmail.com
        "imap_port": 993,
        "smtp_host": "",          # 如 smtp.qq.com / smtp.gmail.com
        "smtp_port": 465,
        "email": "",              # 邮箱地址
        "password": "",           # 授权码（多数邮箱用授权码而非登录密码）
        "subject_filter": "结缘",  # 主题包含此关键字才视为申请（空=全部未读）
        "poll_interval_min": 10,  # 轮询间隔（分钟）
        "code_ttl_days": 7,       # 发出的码有效期
        "from_name": "Anima",     # 回信显示名
        "reply_subject": "你的 Anima 结缘码 🪔",
        "reply_template": (
            "你好，\n\n"
            "感谢你想认识 Anima。这是你的专属结缘码：\n\n"
            "    {code}\n\n"
            "在 Anima 首次启动时输入它即可入门（{ttl} 天内有效）。\n\n"
            "愿我们好好相处。\n— Anima"
        ),
    }


def load_config() -> dict:
    cfg = _default_cfg()
    if _CFG_PATH.exists():
        try:
            cfg.update(json.loads(_CFG_PATH.read_text("utf-8")) or {})
        except Exception as e:
            log.warning("读取邮箱管家配置失败: %s", e)
    return cfg


def save_config(patch: dict) -> dict:
    """合并保存。password 传空/掩码表示不修改。"""
    cfg = load_config()
    for k, v in (patch or {}).items():
        if k == "password" and v in (None, "", "********"):
            continue
        if k in _default_cfg():
            cfg[k] = v
    _CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    return cfg


def config_public() -> dict:
    """前端安全版：不回传明文密码。"""
    cfg = load_config()
    return {
        "enabled":       cfg.get("enabled", False),
        "imap_host":     cfg.get("imap_host", ""),
        "imap_port":     cfg.get("imap_port", 993),
        "smtp_host":     cfg.get("smtp_host", ""),
        "smtp_port":     cfg.get("smtp_port", 465),
        "email":         cfg.get("email", ""),
        "has_password":  bool(cfg.get("password")),
        "subject_filter": cfg.get("subject_filter", "结缘"),
        "poll_interval_min": cfg.get("poll_interval_min", 10),
        "code_ttl_days": cfg.get("code_ttl_days", 7),
        "from_name":     cfg.get("from_name", "Anima"),
        "reply_subject": cfg.get("reply_subject", ""),
    }


# ── 已发送账本（防重复）──────────────────────────────────
def _load_sent() -> dict:
    if _SENT_PATH.exists():
        try:
            return json.loads(_SENT_PATH.read_text("utf-8")) or {}
        except Exception:
            pass
    return {}


def _mark_sent(addr: str, code: str) -> None:
    data = _load_sent()
    data[addr.lower()] = {"code": code, "at": datetime.now(timezone.utc).isoformat()}
    try:
        _SENT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def _already_sent(addr: str) -> bool:
    return addr.lower() in _load_sent()


# ── 阻塞 IMAP/SMTP（在线程池里跑）────────────────────────
def _decode(s) -> str:
    try:
        return str(make_header(decode_header(s or "")))
    except Exception:
        return s or ""


def _fetch_new_senders(cfg: dict) -> list[str]:
    """连 IMAP，找符合主题过滤的未读邮件，返回申请人邮箱列表，并标记已读。"""
    host = cfg.get("imap_host"); port = int(cfg.get("imap_port") or 993)
    user = cfg.get("email"); pwd = cfg.get("password")
    subj_filter = (cfg.get("subject_filter") or "").strip()
    if not (host and user and pwd):
        return []
    senders: list[str] = []
    try:
        M = imaplib.IMAP4_SSL(host, port)
        M.login(user, pwd)
        M.select("INBOX")
        typ, data = M.search(None, "UNSEEN")
        if typ != "OK":
            M.logout(); return []
        for num in data[0].split():
            typ, msg_data = M.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode(msg.get("Subject", ""))
            if subj_filter and subj_filter not in subject:
                continue  # 不匹配主题 → 留作未读，不处理
            _, addr = parseaddr(msg.get("From", ""))
            if addr:
                senders.append(addr)
                M.store(num, "+FLAGS", "\\Seen")   # 标记已读
        M.logout()
    except Exception as e:
        log.warning("IMAP 轮询失败: %s", e)
    return senders


def _send_code(cfg: dict, to_addr: str, code: str) -> bool:
    """SMTP 发码给申请人。"""
    host = cfg.get("smtp_host"); port = int(cfg.get("smtp_port") or 465)
    user = cfg.get("email"); pwd = cfg.get("password")
    if not (host and user and pwd):
        return False
    ttl = int(cfg.get("code_ttl_days") or 7)
    body = (cfg.get("reply_template") or _default_cfg()["reply_template"]).format(code=code, ttl=ttl)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = str(make_header([(cfg.get("reply_subject", "Anima"), "utf-8")]))
    msg["From"] = formataddr((str(make_header([(cfg.get("from_name", "Anima"), "utf-8")])), user))
    msg["To"] = to_addr
    try:
        if port == 465:
            s = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            s = smtplib.SMTP(host, port, timeout=30); s.starttls()
        s.login(user, pwd)
        s.sendmail(user, [to_addr], msg.as_string())
        s.quit()
        return True
    except Exception as e:
        log.warning("SMTP 发码失败 → %s: %s", to_addr, e)
        return False


def test_connection(cfg: dict) -> dict:
    """校验 IMAP + SMTP 登录是否成功（不发信、不改邮件）。"""
    host = cfg.get("imap_host"); user = cfg.get("email"); pwd = cfg.get("password")
    if not (host and user and pwd):
        return {"ok": False, "error": "请填写完整：IMAP 主机 / 邮箱 / 授权码"}
    # IMAP
    try:
        M = imaplib.IMAP4_SSL(host, int(cfg.get("imap_port") or 993))
        M.login(user, pwd); M.select("INBOX"); M.logout()
    except Exception as e:
        return {"ok": False, "error": f"IMAP 登录失败：{e}"}
    # SMTP
    try:
        sport = int(cfg.get("smtp_port") or 465)
        if sport == 465:
            s = smtplib.SMTP_SSL(cfg.get("smtp_host"), sport, timeout=20)
        else:
            s = smtplib.SMTP(cfg.get("smtp_host"), sport, timeout=20); s.starttls()
        s.login(user, pwd); s.quit()
    except Exception as e:
        return {"ok": False, "error": f"SMTP 登录失败：{e}"}
    return {"ok": True}


# ── 管家单例 ────────────────────────────────────────────
class InviteMailer:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._last_poll: str | None = None
        self._last_result: str = ""
        self._sent_count = 0

    def configure(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def _poll_once(self) -> dict:
        cfg = load_config()
        if not cfg.get("enabled"):
            return {"polled": False}
        self._last_poll = datetime.now(timezone.utc).isoformat()
        senders = await asyncio.to_thread(_fetch_new_senders, cfg)
        sent = 0
        for addr in senders:
            if _already_sent(addr):
                continue
            code = await _invite.mint_code("mailer", int(cfg.get("code_ttl_days") or 7))
            if not code:
                log.warning("铸码失败（Supabase 未配置？），跳过 %s", addr)
                continue
            ok = await asyncio.to_thread(_send_code, cfg, addr, code)
            if ok:
                _mark_sent(addr, code)
                sent += 1
                self._sent_count += 1
                log.info("已向 %s 发出结缘码 %s", addr, code)
        self._last_result = f"轮询到 {len(senders)} 封，新发 {sent} 枚码"
        return {"polled": True, "found": len(senders), "sent": sent}

    async def _loop_run(self):
        self._running = True
        # 启动稍等，避免和后端其它启动项抢资源
        await asyncio.sleep(15)
        while self._running:
            cfg = load_config()
            if not cfg.get("enabled"):
                break
            try:
                await self._poll_once()
            except Exception as e:
                log.warning("邮箱管家轮询异常: %s", e)
            interval = max(1, int(cfg.get("poll_interval_min") or 10))
            for _ in range(interval * 60):
                if not self._running:
                    break
                await asyncio.sleep(1)
        self._running = False

    def start(self) -> dict:
        cfg = load_config()
        if not cfg.get("enabled"):
            return {"ok": False, "error": "未启用"}
        if not _invite._configured():
            return {"ok": False, "error": "Supabase 未配置，无法铸码"}
        if self._running:
            return {"ok": True, "already": True}
        loop = self._loop or asyncio.get_event_loop()
        self._task = loop.create_task(self._loop_run())
        return {"ok": True}

    def stop(self) -> dict:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        return {"ok": True}

    def status(self) -> dict:
        return {
            "running": self._running,
            "last_poll": self._last_poll,
            "last_result": self._last_result,
            "sent_total": self._sent_count,
        }

    async def poll_now(self) -> dict:
        """手动触发一次轮询（设置页测试用）。"""
        return await self._poll_once()


mailer = InviteMailer()
