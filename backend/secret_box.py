#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
透明密钥加密 — Anima
------------------------------------------------------------
把 config.yaml 里的 API Key / Token 做静态加密（encryption at rest）。
加密密钥存在独立的受限文件 ~/.anima/.secret.key（与 config.yaml 分离）。

威胁模型（诚实声明）：
  ✓ 防 config.yaml 被同步到云盘 / 截图 / 误提交 git → 里面只是密文
  ✓ 防其它低权限进程读 config（Unix 下 .secret.key 为 0600）
  ✗ 不防能完整读取本用户主目录的攻击者（本地应用必须能无人值守解密，
    这是所有本地应用的共性，不做夸大宣称）

设计要点：
  - 加密失败一律降级返回原文，绝不丢用户数据
  - 解密失败返回空串（而不是把密文当 key 用，避免拿错误 key 调 API）
  - 幂等：对已加密值再加密是 no-op
  - 旧明文自动兼容（is_encrypted 判断 marker 前缀）
"""
import logging
import os
import stat
from pathlib import Path

_MARKER = "enc:v1:"
log = logging.getLogger("anima.secret")
_fernet = None          # 懒加载缓存
_init_failed = False     # 初始化失败标志，避免反复重试刷屏


def _key_path() -> Path:
    # 固定放引导目录，不随数据目录迁移（与 config.yaml 同处 ~/.anima）
    return Path.home() / ".anima" / ".secret.key"


def _load_or_create_key() -> bytes:
    from cryptography.fernet import Fernet
    p = _key_path()
    if p.exists():
        try:
            data = p.read_bytes().strip()
            if data:
                return data
        except Exception as e:
            log.error("读取密钥文件失败: %s", e)
    # 生成新密钥并尽量收紧权限
    key = Fernet.generate_key()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(key)
        try:
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        except Exception:
            pass
        if os.name == "nt":
            # Windows: 设隐藏属性（best-effort）
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(str(p), 0x02)
            except Exception:
                pass
        log.info("已生成新的本地加密密钥: %s", p)
    except Exception as e:
        log.error("写入密钥文件失败（本次会话用临时密钥）: %s", e)
    return key


def _box():
    global _fernet, _init_failed
    if _fernet is None and not _init_failed:
        try:
            from cryptography.fernet import Fernet
            _fernet = Fernet(_load_or_create_key())
        except Exception as e:
            log.error("初始化加密器失败，密钥将以明文降级处理: %s", e)
            _init_failed = True
            _fernet = None
    return _fernet


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(_MARKER)


def looks_sensitive(leaf_name: str) -> bool:
    """按字段名判断该配置项是否应加密（URL 等不匹配，保持可读）。"""
    if not isinstance(leaf_name, str):
        return False
    n = leaf_name.lower()
    return (n.endswith("_key") or n.endswith("_token") or n.endswith("_pass")
            or n.endswith("password") or "secret" in n)


def encrypt(plaintext):
    """加密明文 → 带 marker 的密文。空值/非串/已加密/失败 → 原样返回。"""
    if not isinstance(plaintext, str) or plaintext == "":
        return plaintext
    if is_encrypted(plaintext):
        return plaintext
    box = _box()
    if box is None:
        return plaintext
    try:
        token = box.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return _MARKER + token
    except Exception as e:
        log.error("加密失败，降级明文: %s", e)
        return plaintext


def decrypt(value):
    """解密；非密文原样返回（兼容旧明文）。解不开返回空串。"""
    if not is_encrypted(value):
        return value
    box = _box()
    if box is None:
        return value
    try:
        from cryptography.fernet import InvalidToken
        token = value[len(_MARKER):]
        try:
            return box.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken:
            log.error("密文无法解密（密钥不匹配？），返回空串以免误用")
            return ""
    except Exception as e:
        log.error("解密异常: %s", e)
        return ""


def encrypt_sensitive_tree(updates: dict) -> dict:
    """
    深拷贝 updates，并把其中所有"敏感叶子字段"加密。
    供 save_user_config 在写盘前调用。原 dict 不被修改。
    """
    def _walk(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if isinstance(v, (dict, list)):
                    out[k] = _walk(v)
                elif looks_sensitive(k) and isinstance(v, str) and v:
                    out[k] = encrypt(v)
                else:
                    out[k] = v
            return out
        if isinstance(node, list):
            return [_walk(x) for x in node]
        return node
    try:
        return _walk(updates)
    except Exception as e:
        log.error("加密配置树失败，原样写入: %s", e)
        return updates
