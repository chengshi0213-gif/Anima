#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechat_crypto.py — 微信/企业微信回调消息加解密（WXBizMsgCrypt 等价实现）

企业微信「应用」与微信公众号「安全模式」都用同一套加解密协议：
  - AES-256-CBC，密钥 = base64decode(EncodingAESKey + "=")（32 字节），IV = 密钥前 16 字节
  - 明文结构 = random(16) + msg_len(4字节网络序) + msg + receiveid
  - 签名 = sha1(sorted([token, timestamp, nonce, encrypt]) 拼接) 的十六进制

receiveid：企业微信为 CorpID，公众号为 AppID。验签 + 校验 receiveid 共同保证回调真伪，
因此回调端点无需我们自己的 Bearer Token。

依赖 cryptography（已在 requirements 中）。纯函数，便于单元测试加解密往返。
"""
from __future__ import annotations

import base64
import hashlib
import os
import struct
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class WeChatCryptoError(Exception):
    pass


def _aes_key(encoding_aes_key: str) -> bytes:
    if not encoding_aes_key or len(encoding_aes_key) != 43:
        raise WeChatCryptoError("EncodingAESKey 必须是 43 位字符串")
    key = base64.b64decode(encoding_aes_key + "=")
    if len(key) != 32:
        raise WeChatCryptoError("EncodingAESKey 解码后不是 32 字节")
    return key


def _pkcs7_pad(data: bytes, block: int = 32) -> bytes:
    pad = block - (len(data) % block)
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    pad = data[-1]
    if pad < 1 or pad > 32:
        pad = 0
    return data[:-pad] if pad else data


def signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    """计算消息签名（GET 验证 URL 与 POST 收消息共用）。"""
    items = sorted([token or "", timestamp or "", nonce or "", encrypt or ""])
    return hashlib.sha1("".join(items).encode("utf-8")).hexdigest()


def verify_signature(token: str, msg_signature: str, timestamp: str,
                     nonce: str, encrypt: str) -> bool:
    try:
        return signature(token, timestamp, nonce, encrypt) == (msg_signature or "")
    except Exception:
        return False


def encrypt_msg(plaintext: str, encoding_aes_key: str, receiveid: str) -> str:
    """把回复明文加密为 base64 的 Encrypt 串。"""
    key = _aes_key(encoding_aes_key)
    iv = key[:16]
    msg = plaintext.encode("utf-8")
    rand = os.urandom(16)
    payload = rand + struct.pack(">I", len(msg)) + msg + (receiveid or "").encode("utf-8")
    padded = _pkcs7_pad(payload)
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = enc.update(padded) + enc.finalize()
    return base64.b64encode(ct).decode("utf-8")


def decrypt_msg(encrypt_b64: str, encoding_aes_key: str,
                receiveid: Optional[str] = None) -> str:
    """解密 Encrypt 串，返回内层明文。若给了 receiveid 则校验一致性。"""
    key = _aes_key(encoding_aes_key)
    iv = key[:16]
    ct = base64.b64decode(encrypt_b64)
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = _pkcs7_unpad(dec.update(ct) + dec.finalize())
    if len(plain) < 20:
        raise WeChatCryptoError("解密结果过短")
    msg_len = struct.unpack(">I", plain[16:20])[0]  # 4 字节网络序（大端）
    msg = plain[20:20 + msg_len].decode("utf-8")
    rid = plain[20 + msg_len:].decode("utf-8")
    if receiveid is not None and receiveid != "" and rid != receiveid:
        raise WeChatCryptoError(f"receiveid 不匹配（期望 {receiveid}，实得 {rid}）")
    return msg
