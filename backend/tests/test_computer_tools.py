#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""computer_tools 安全闸门测试 — 不真正动鼠标键盘，只验证闸门逻辑。"""
import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import computer_tools as ct
from agent_base import PermissionRequest


@pytest.fixture(autouse=True)
def _isolate_cfg(tmp_path, monkeypatch):
    """每个用例用独立配置文件，互不污染。"""
    cfg = tmp_path / "computer_use.json"
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(ct, "_CFG_PATH", cfg)
    monkeypatch.setattr(ct, "_AUDIT_PATH", audit)
    monkeypatch.setattr(ct, "_SHOT_DIR", tmp_path / "shots")
    yield


def _set_mode(enabled, mode):
    ct.save_config({"enabled": enabled, "mode": mode})


def test_default_is_off():
    cfg = ct.load_config()
    assert cfg["enabled"] is False
    assert cfg["mode"] == "off"


def test_save_forces_off_when_disabled():
    # enabled=False 即便给了 mode=auto 也应被压回 off
    cfg = ct.save_config({"enabled": False, "mode": "auto"})
    assert cfg["mode"] == "off"


def test_guard_blocks_when_off():
    _set_mode(False, "off")
    with pytest.raises(PermissionRequest):
        ct._guard("screen_info", {})


def test_readonly_allows_read_blocks_control():
    _set_mode(True, "readonly")
    # 读取动作放行（不抛）
    ct._guard("screen_info", {})
    ct._guard("screen_capture", {})
    # 控制动作被拦
    with pytest.raises(PermissionRequest):
        ct._guard("mouse_click", {"x": 1, "y": 1})


def test_auto_allows_control():
    _set_mode(True, "auto")
    ct._guard("mouse_click", {"x": 1, "y": 1})
    ct._guard("keyboard_type", {"text": "hi"})


def test_invalid_mode_falls_back_off():
    ct.save_config({"enabled": True, "mode": "nonsense"})
    cfg = ct.load_config()
    assert cfg["mode"] == "off"


def test_confirm_denied_blocks():
    _set_mode(True, "confirm")
    # 没人批准 → request 内部会等待；用极短超时避免拖慢测试
    import computer_tools
    orig = computer_tools._CONFIRM_TIMEOUT
    computer_tools._CONFIRM_TIMEOUT = 0.2
    try:
        with pytest.raises(PermissionRequest):
            ct._guard("mouse_click", {"x": 1, "y": 1})
    finally:
        computer_tools._CONFIRM_TIMEOUT = orig


def test_confirm_approved_passes():
    _set_mode(True, "confirm")
    approved_holder = {}

    def _worker():
        approved_holder["ok"] = None
        try:
            ct._guard("mouse_click", {"x": 5, "y": 5})
            approved_holder["ok"] = True
        except PermissionRequest:
            approved_holder["ok"] = False

    t = threading.Thread(target=_worker)
    t.start()
    # 等 pending 出现，批准它
    for _ in range(50):
        pend = ct.bridge.list_pending()
        if pend:
            ct.bridge.resolve(pend[0]["id"], True)
            break
        time.sleep(0.02)
    t.join(timeout=5)
    assert approved_holder.get("ok") is True


def test_audit_written():
    _set_mode(True, "readonly")
    try:
        ct._guard("mouse_click", {"x": 1, "y": 1})  # 会被拦 + 写审计
    except PermissionRequest:
        pass
    assert ct._AUDIT_PATH.exists()
    lines = ct._AUDIT_PATH.read_text("utf-8").strip().splitlines()
    rec = json.loads(lines[-1])
    assert rec["action"] == "mouse_click"
    assert "blocked" in rec["result"]


def test_tool_defs_and_dispatch_consistent():
    names_defs = {t["function"]["name"] for t in ct.TOOL_DEFS}
    names_disp = set(ct.build_dispatch().keys())
    assert names_defs == names_disp
