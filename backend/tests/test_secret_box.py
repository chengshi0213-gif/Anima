#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""密钥透明加密测试 — secret_box"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import secret_box as sb


def test_roundtrip():
    k = "sk-ant-api03-UNIT-TEST-KEY"
    enc = sb.encrypt(k)
    assert sb.is_encrypted(enc)
    assert not sb.is_encrypted(k)
    assert sb.decrypt(enc) == k


def test_idempotent_encrypt():
    k = "sk-test-123"
    once = sb.encrypt(k)
    twice = sb.encrypt(once)
    # 再加密不应套娃，解密仍得原文
    assert sb.decrypt(twice) == k


def test_empty_and_plaintext_passthrough():
    assert sb.encrypt("") == ""
    assert sb.decrypt("") == ""
    assert sb.decrypt("old-plaintext-key") == "old-plaintext-key"


def test_looks_sensitive():
    for name in ("deepseek_key", "github_token", "anon_key", "smtp_pass",
                 "auth_password", "client_secret"):
        assert sb.looks_sensitive(name), name
    for name in ("glm_url", "name", "port", "model"):
        assert not sb.looks_sensitive(name), name


def test_encrypt_sensitive_tree():
    tree = {
        "api": {"deepseek_key": "sk-real", "glm_url": "https://x.com"},
        "user": {"name": "Hilda"},
        "supabase": {"anon_key": "pub-anon-123"},
    }
    out = sb.encrypt_sensitive_tree(tree)
    assert sb.is_encrypted(out["api"]["deepseek_key"])
    assert sb.is_encrypted(out["supabase"]["anon_key"])
    assert out["api"]["glm_url"] == "https://x.com"   # URL 不加密
    assert out["user"]["name"] == "Hilda"             # 普通字段不加密
    # 原 dict 不被就地修改
    assert tree["api"]["deepseek_key"] == "sk-real"


def test_decrypt_garbage_returns_empty():
    # 带 marker 但内容不可解 → 返回空串（不把密文当 key 用）
    assert sb.decrypt("enc:v1:not-a-valid-token") == ""
