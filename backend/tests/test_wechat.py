#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信/企业微信 加解密往返 + 签名 + 配置掩码测试。"""
import base64
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import wechat_crypto as wxc
import wechat_bot as wb


# 43 位合法 EncodingAESKey（base64，解码后 32 字节）
_AES_KEY = base64.b64encode(os.urandom(32)).decode()[:43]
_RECEIVEID = "wwabc123corp"
_TOKEN = "mytoken"


def test_aes_key_validation():
    with pytest.raises(wxc.WeChatCryptoError):
        wxc._aes_key("tooshort")


def test_encrypt_decrypt_roundtrip():
    plain = "你好，Anima！hello 123 🐉"
    enc = wxc.encrypt_msg(plain, _AES_KEY, _RECEIVEID)
    dec = wxc.decrypt_msg(enc, _AES_KEY, _RECEIVEID)
    assert dec == plain


def test_decrypt_receiveid_mismatch():
    enc = wxc.encrypt_msg("hi", _AES_KEY, _RECEIVEID)
    with pytest.raises(wxc.WeChatCryptoError):
        wxc.decrypt_msg(enc, _AES_KEY, "wrong_corp")


def test_signature_stable_and_verify():
    sig = wxc.signature(_TOKEN, "1700000000", "nonce123", "ENCRYPTED")
    assert wxc.verify_signature(_TOKEN, sig, "1700000000", "nonce123", "ENCRYPTED")
    assert not wxc.verify_signature(_TOKEN, "deadbeef", "1700000000", "nonce123", "ENCRYPTED")


def test_xml_field_extract():
    xml = ("<xml><ToUserName><![CDATA[corp]]></ToUserName>"
           "<MsgType><![CDATA[text]]></MsgType>"
           "<Content><![CDATA[在吗]]></Content>"
           "<MsgId>123456</MsgId></xml>")
    assert wb._xml_field(xml, "MsgType") == "text"
    assert wb._xml_field(xml, "Content") == "在吗"
    assert wb._xml_field(xml, "MsgId") == "123456"
    assert wb._xml_field(xml, "Nope") == ""


@pytest.fixture
def _iso_cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(wb, "_CFG_PATH", tmp_path / "wechat.json")
    wb._TOKEN_CACHE.clear()
    yield


def test_config_masks_secrets(_iso_cfg):
    wb.save_config({
        "provider": "wecom", "token": _TOKEN, "aes_key": _AES_KEY,
        "corp_id": "corp1", "corp_secret": "sekret", "agent_id": "1000002",
        "default_agent": "tianyuan", "enabled": True,
    })
    pub = wb.config_public()
    assert pub["has_aes_key"] is True
    assert pub["has_corp_secret"] is True
    assert "sekret" not in str(pub)        # 明文密钥不外泄
    assert pub["receiveid"] == "corp1"
    assert pub["default_agent"] == "tianyuan"


def test_empty_secret_keeps_existing(_iso_cfg):
    wb.save_config({"provider": "wecom", "aes_key": _AES_KEY, "corp_secret": "orig"})
    wb.save_config({"corp_secret": ""})    # 留空不改
    cfg = wb.load_config()
    assert cfg["corp_secret"] == "orig"
    assert cfg["aes_key"] == _AES_KEY


def test_invalid_provider_falls_back(_iso_cfg):
    wb.save_config({"provider": "telegram"})  # 非法 → 被忽略，保持默认 wecom
    assert wb.load_config()["provider"] == "wecom"


def test_url_verify_roundtrip(_iso_cfg):
    wb.save_config({"provider": "wecom", "token": _TOKEN, "aes_key": _AES_KEY,
                    "corp_id": _RECEIVEID})
    echo_plain = "1234567890echo"
    echostr = wxc.encrypt_msg(echo_plain, _AES_KEY, _RECEIVEID)
    sig = wxc.signature(_TOKEN, "ts", "nonce", echostr)
    out = wb.bot.verify_url(sig, "ts", "nonce", echostr)
    assert out == echo_plain
    # 错误签名 → None
    assert wb.bot.verify_url("bad", "ts", "nonce", echostr) is None
