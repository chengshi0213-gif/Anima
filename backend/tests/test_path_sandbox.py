#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文件访问护栏测试 — path_sandbox"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import path_sandbox as ps


def _home() -> str:
    return str(Path.home())


def test_block_ssh_private_key():
    ok, reason = ps.check_path(_home() + "/.ssh/id_rsa")
    assert not ok and reason


def test_block_ssh_dir_any_file():
    ok, _ = ps.check_path(_home() + "/.ssh/known_hosts")
    assert not ok


def test_block_aws_credentials():
    ok, _ = ps.check_path(_home() + "/.aws/credentials")
    assert not ok


def test_block_anima_secret_key():
    ok, _ = ps.check_path(_home() + "/.anima/.secret.key")
    assert not ok


def test_block_anima_config():
    ok, _ = ps.check_path(_home() + "/.anima/config.yaml")
    assert not ok


def test_block_named_private_keys():
    for name in ("id_rsa", "id_ed25519", "id_ecdsa"):
        ok, _ = ps.check_path(name)
        assert not ok, name


def test_allow_normal_dev_paths():
    for p in ("E:/AI/workspace/Anima/backend/xi_worker.py",
              _home() + "/Documents/notes.md",
              "./README.md"):
        ok, reason = ps.check_path(p, write=False)
        assert ok, f"{p} 不该被拦: {reason}"


def test_allow_normal_write():
    ok, reason = ps.check_path(_home() + "/Documents/draft.txt", write=True)
    assert ok, reason


def test_block_system_dir_write():
    import os
    target = (os.environ.get("SystemRoot", "C:/Windows") + "/evil.exe"
              if os.name == "nt" else "/etc/evil.conf")
    ok, _ = ps.check_path(target, write=True)
    assert not ok


def test_empty_path_rejected():
    ok, _ = ps.check_path("")
    assert not ok


def test_custom_denylist(monkeypatch, tmp_path):
    """config.security.denied_paths 自定义黑名单生效。"""
    secret_dir = tmp_path / "vault"
    secret_dir.mkdir()
    target = str(secret_dir / "x.txt")

    import config as _cfg
    orig = _cfg._get

    def fake_get(key, default=None):
        if key == "security.denied_paths":
            return [str(secret_dir)]
        return orig(key, default)

    monkeypatch.setattr(_cfg, "_get", fake_get)
    ok, _ = ps.check_path(target, write=False)
    assert not ok
