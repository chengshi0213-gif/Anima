#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anima 会员系统 — 激活码验证 + 权限管理

机制：
  - 激活码格式: ANIMA-XXXX-XXXX-XXXX（16 位 hex，加前缀和分隔符）
  - 激活码内嵌信息：tier(free/pro) + 过期时间 + HMAC 签名
  - 激活后写入 ~/.anima/config.yaml 的 membership 节
  - 本地验证，不需联网（Phase 1 适用）

权限：
  free — 8 个基础 Skill + 自建工作流
  pro  — 全部 30 个 Skill + 预置工作流模板库
"""
import hashlib
import hmac
import struct
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── 签名密钥（编译进二进制，Phase 1 足够安全）──
_SECRET = b"anima-horizon-2026-rebuild"

# ── Tier 定义 ──
TIER_FREE = "free"
TIER_PRO  = "pro"


def generate_license(days: int = 365, tier: str = TIER_PRO) -> str:
    """生成激活码（你自己用，不暴露给用户）

    Args:
        days: 有效天数
        tier: 会员等级 "pro"
    Returns:
        激活码字符串 "ANIMA-XXXX-XXXX-XXXX"
    """
    # 编码: tier(1B) + expire_ts(4B) + random(3B) = 8 bytes payload
    tier_byte = 0x01 if tier == TIER_PRO else 0x00
    expire_ts = int(time.time()) + days * 86400
    import secrets
    rand = secrets.token_bytes(3)
    payload = struct.pack(">BI", tier_byte, expire_ts) + rand  # 8 bytes

    # HMAC 签名取前 4 bytes
    sig = hmac.new(_SECRET, payload, hashlib.sha256).digest()[:4]
    raw = payload + sig  # 12 bytes total

    # 编码为 hex，加格式
    hex_str = raw.hex().upper()
    return f"ANIMA-{hex_str[:4]}-{hex_str[4:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:24]}"


def validate_license(code: str) -> dict:
    """验证激活码

    Returns:
        {"valid": True, "tier": "pro", "expires": "2027-05-26", "days_left": 365}
        或 {"valid": False, "error": "原因"}
    """
    if not code:
        return {"valid": False, "error": "激活码为空"}

    # 清理格式
    clean = code.replace("ANIMA-", "").replace("-", "").strip()
    if len(clean) != 24:
        return {"valid": False, "error": "激活码格式错误"}

    try:
        raw = bytes.fromhex(clean)
    except ValueError:
        return {"valid": False, "error": "激活码包含无效字符"}

    if len(raw) != 12:
        return {"valid": False, "error": "激活码长度错误"}

    payload = raw[:8]
    sig = raw[8:12]

    # 验签
    expected_sig = hmac.new(_SECRET, payload, hashlib.sha256).digest()[:4]
    if not hmac.compare_digest(sig, expected_sig):
        return {"valid": False, "error": "激活码无效"}

    # 解码
    tier_byte = payload[0]
    expire_ts = struct.unpack(">I", payload[1:5])[0]
    tier = TIER_PRO if tier_byte == 0x01 else TIER_FREE

    # 检查过期
    now = int(time.time())
    if now > expire_ts:
        expire_date = datetime.fromtimestamp(expire_ts).strftime("%Y-%m-%d")
        return {"valid": False, "error": f"激活码已过期（{expire_date}）"}

    days_left = (expire_ts - now) // 86400
    expire_date = datetime.fromtimestamp(expire_ts).strftime("%Y-%m-%d")

    return {
        "valid": True,
        "tier": tier,
        "expires": expire_date,
        "days_left": days_left,
    }


def get_membership() -> dict:
    """读取当前会员状态

    Returns:
        {"tier": "free|pro", "expires": "2027-...", "days_left": N, "active": bool}
    """
    try:
        from config import _get
        code = _get("membership.license_key", "")
        if not code:
            return {"tier": TIER_FREE, "active": False, "expires": None, "days_left": 0}

        result = validate_license(code)
        if result["valid"]:
            return {
                "tier": result["tier"],
                "active": True,
                "expires": result["expires"],
                "days_left": result["days_left"],
            }
        else:
            # 激活码无效或过期，降级为免费
            return {"tier": TIER_FREE, "active": False, "expires": None,
                    "days_left": 0, "error": result["error"]}
    except Exception:
        return {"tier": TIER_FREE, "active": False, "expires": None, "days_left": 0}


def activate(code: str) -> dict:
    """激活会员

    Returns:
        {"ok": True, "tier": "pro", ...} 或 {"ok": False, "error": "..."}
    """
    result = validate_license(code)
    if not result["valid"]:
        return {"ok": False, "error": result["error"]}

    # 写入 config.yaml
    from config import save_user_config
    save_user_config({"membership": {"license_key": code}})

    return {
        "ok": True,
        "tier": result["tier"],
        "expires": result["expires"],
        "days_left": result["days_left"],
        "message": f"欢迎加入 Anima Pro！有效期至 {result['expires']}",
    }


def deactivate() -> dict:
    """取消激活（退回免费）"""
    from config import save_user_config
    save_user_config({"membership": {"license_key": ""}})
    return {"ok": True, "tier": TIER_FREE}


def is_pro() -> bool:
    """快速检查：当前是否为 Pro 会员"""
    m = get_membership()
    return m["tier"] == TIER_PRO and m.get("active", False)
