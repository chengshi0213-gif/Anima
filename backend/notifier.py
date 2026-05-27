#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通知推送 — 飞书 / 钉钉 Webhook
Agent 任务完成后推送摘要到群
"""
import hashlib
import hmac
import json
import time
import urllib.request
from base64 import b64encode
from pathlib import Path

from config import DATA_DIR

NOTIF_CFG_FILE = DATA_DIR / "notifier_config.json"


def _load_cfg() -> dict:
    if NOTIF_CFG_FILE.exists():
        return json.loads(NOTIF_CFG_FILE.read_text("utf-8"))
    return {"channels": []}


def _save_cfg(cfg: dict):
    NOTIF_CFG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")


# ── 飞书 ────────────────────────────────────────────
def _feishu_sign(secret: str, timestamp: int) -> str:
    s = f"{timestamp}\n{secret}"
    return b64encode(hmac.new(s.encode("utf-8"), digestmod=hashlib.sha256).digest()).decode()


def send_feishu(webhook_url: str, title: str, content: str, secret: str = "") -> bool:
    timestamp = int(time.time())
    payload: dict = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": [[{"tag": "text", "text": content[:1800]}]],
                }
            }
        },
    }
    if secret:
        payload["timestamp"] = str(timestamp)
        payload["sign"]      = _feishu_sign(secret, timestamp)
    try:
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(webhook_url, data=data,
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read())
        return result.get("code", -1) == 0 or result.get("StatusCode", -1) == 0
    except Exception as e:
        print(f"[Notifier] 飞书推送失败: {e}")
        return False


# ── 钉钉 ────────────────────────────────────────────
def _dingtalk_sign(secret: str) -> tuple[int, str]:
    timestamp = int(time.time() * 1000)
    s = f"{timestamp}\n{secret}"
    sig = b64encode(hmac.new(secret.encode("utf-8"), s.encode("utf-8"), digestmod=hashlib.sha256).digest()).decode()
    return timestamp, sig


def send_dingtalk(webhook_url: str, title: str, content: str, secret: str = "") -> bool:
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text":  f"### {title}\n\n{content[:2000]}\n\n> 来自 Anima",
        },
    }
    url = webhook_url
    if secret:
        ts, sig = _dingtalk_sign(secret)
        from urllib.parse import quote
        url = f"{webhook_url}&timestamp={ts}&sign={quote(sig)}"
    try:
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(url, data=data,
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read())
        return result.get("errcode", -1) == 0
    except Exception as e:
        print(f"[Notifier] 钉钉推送失败: {e}")
        return False


# ── 统一推送接口 ─────────────────────────────────────
def push(title: str, content: str) -> list[dict]:
    """推送到所有已配置的 channel，返回各 channel 结果"""
    cfg      = _load_cfg()
    results  = []
    for ch in cfg.get("channels", []):
        if not ch.get("enabled", True):
            continue
        t   = ch.get("type", "")
        url = ch.get("webhook", "")
        sec = ch.get("secret", "")
        if not url:
            continue
        ok = False
        if t == "feishu":
            ok = send_feishu(url, title, content, sec)
        elif t == "dingtalk":
            ok = send_dingtalk(url, title, content, sec)
        results.append({"channel": ch.get("name", t), "ok": ok})
    return results


# ── 配置 CRUD ────────────────────────────────────────
def list_channels() -> list[dict]:
    return _load_cfg().get("channels", [])


def add_channel(name: str, ch_type: str, webhook: str, secret: str = "") -> dict:
    import uuid
    cfg = _load_cfg()
    ch  = {"id": str(uuid.uuid4())[:8], "name": name, "type": ch_type,
           "webhook": webhook, "secret": secret, "enabled": True}
    cfg.setdefault("channels", []).append(ch)
    _save_cfg(cfg)
    return ch


def delete_channel(ch_id: str) -> bool:
    cfg = _load_cfg()
    before = len(cfg.get("channels", []))
    cfg["channels"] = [c for c in cfg.get("channels", []) if c["id"] != ch_id]
    if len(cfg["channels"]) < before:
        _save_cfg(cfg)
        return True
    return False


def test_channel(ch_id: str) -> bool:
    cfg = _load_cfg()
    ch  = next((c for c in cfg.get("channels", []) if c["id"] == ch_id), None)
    if not ch:
        return False
    return push("🔮 Anima 测试推送", "连接测试成功！Anima Agent 任务完成后将通过此渠道通知你。")
