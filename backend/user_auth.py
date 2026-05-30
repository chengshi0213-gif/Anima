#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
user_auth.py — 本地密码登录（离线，不联网）

设计原则：
- 密码永远不明文存储，使用 PBKDF2-HMAC-SHA256 + 随机盐。
- 凭证存入 ~/.anima/config.yaml 的 `auth` 节，与 API Key 同一份配置。
- 出生信息（生日/时辰/出生地）存入 `user.birth` 节，喂给晞做真实命理/星历计算。
- 忘记密码：复用 membership.py 的激活码体系做离线重置（无需邮箱/联网）。

注意：本模块只负责"用户身份"，与 routes/auth.py 的传输层 Token 无关。
"""
import os
import hmac
import hashlib
import secrets
from typing import Optional

import config as _config

# ── PBKDF2 参数 ─────────────────────────────────────────
_ALGO = "pbkdf2_sha256"
_ITERATIONS = 240_000
_SALT_BYTES = 16
_DKLEN = 32


def _hash_password(password: str, salt: bytes, iterations: int = _ITERATIONS) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=_DKLEN)
    return dk.hex()


def _encode(salt: bytes, hash_hex: str, iterations: int = _ITERATIONS) -> str:
    """编码为单字符串：algo$iterations$salt_hex$hash_hex"""
    return f"{_ALGO}${iterations}${salt.hex()}${hash_hex}"


def _decode(stored: str):
    """解析存储串，返回 (iterations, salt_bytes, hash_hex)。失败抛 ValueError。"""
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != _ALGO:
        raise ValueError("unsupported password hash format")
    iterations = int(parts[1])
    salt = bytes.fromhex(parts[2])
    return iterations, salt, parts[3]


# ── 对外 API ────────────────────────────────────────────
def is_password_set() -> bool:
    """是否已设置过登录密码。"""
    return bool(_config._get("auth.password", ""))


def set_password(password: str) -> None:
    """首次设置 / 重置密码。会覆盖旧密码。"""
    if not password or len(password) < 4:
        raise ValueError("密码至少 4 位")
    salt = secrets.token_bytes(_SALT_BYTES)
    hash_hex = _hash_password(password, salt)
    stored = _encode(salt, hash_hex)
    _config.save_user_config({"auth": {"password": stored}})


def verify_password(password: str) -> bool:
    """校验密码。使用恒定时间比较防时序攻击。"""
    stored = _config._get("auth.password", "")
    if not stored:
        return False
    try:
        iterations, salt, expected = _decode(stored)
    except Exception:
        return False
    actual = _hash_password(password, salt, iterations)
    return hmac.compare_digest(actual, expected)


def reset_password_with_code(code: str, new_password: str) -> bool:
    """用激活码离线重置密码。激活码有效则设置新密码并返回 True。"""
    try:
        import membership
        info = membership.validate_license(code)
    except Exception:
        return False
    if not info or not info.get("valid"):
        return False
    set_password(new_password)
    return True


# ── 出生信息（喂给晞做命理/星历）────────────────────────
def save_birth_info(birth: dict) -> None:
    """
    保存出生信息到 user.birth。
    期望字段：date(YYYY-MM-DD), time(HH:MM 可空), place(出生地文本),
              lng/lat(可选经纬度), tz(时区，可选), gender(可选)。
    """
    cleaned = {}
    for k in ("date", "time", "place", "lng", "lat", "tz", "gender", "calendar"):
        v = birth.get(k)
        if v not in (None, ""):
            cleaned[k] = v
    if cleaned:
        _config.save_user_config({"user": {"birth": cleaned}})


def get_birth_info() -> dict:
    b = _config._get("user.birth", {})
    return b if isinstance(b, dict) else {}
