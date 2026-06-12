#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_room.py — v1.2.2 D8 房间感知 + register 联动单元测试 (pytest)

覆盖：
  - resolve_room(None) → daily + companion + XiWorker
  - resolve_room("non_git_dir") → workspace + focused + ExecutorWorker + is_repo=False
  - resolve_room("git_dir") → workspace + focused + ExecutorWorker + is_repo=True
  - RoomConfig.register_fragment 属性
  - capabilities.build(..., register="focused") 把 register 片段置于 fragments[0]

运行:
    cd E:\\AI\\workspace\\Anima\\backend
    python -m pytest tests/test_room.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import room  # noqa: E402


def test_resolve_room_none():
    cfg = room.resolve_room(None)
    assert cfg.room == room.ROOM_DAILY
    assert cfg.is_repo is False
    assert cfg.register == room.REGISTER_COMPANION
    assert cfg.worker_cls == "XiWorker"
    assert cfg.default_effort == "normal"


def test_resolve_room_empty_string():
    cfg = room.resolve_room("")
    assert cfg.room == room.ROOM_DAILY


def test_resolve_room_non_git_dir(tmp_path):
    cfg = room.resolve_room(str(tmp_path))
    assert cfg.room == room.ROOM_WORK
    assert cfg.is_repo is False
    assert cfg.register == room.REGISTER_FOCUSED
    assert cfg.worker_cls == "ExecutorWorker"


def test_resolve_room_git_dir(tmp_path):
    (tmp_path / ".git").mkdir()
    cfg = room.resolve_room(str(tmp_path))
    assert cfg.room == room.ROOM_WORK
    assert cfg.is_repo is True
    assert cfg.register == room.REGISTER_FOCUSED
    assert cfg.worker_cls == "ExecutorWorker"


def test_register_fragment_property():
    cfg = room.resolve_room(None)
    assert "此刻的你" in cfg.register_fragment
    assert "温柔" in cfg.register_fragment

    cfg2 = room.RoomConfig("work", True, room.REGISTER_FOCUSED, "ExecutorWorker", "normal")
    assert "工作台" in cfg2.register_fragment


def test_register_fragments_dict():
    assert room.REGISTER_COMPANION in room.REGISTER_FRAGMENTS
    assert room.REGISTER_FOCUSED in room.REGISTER_FRAGMENTS
    assert "此刻的你" in room.REGISTER_FRAGMENTS[room.REGISTER_COMPANION]
    assert "此刻的你" in room.REGISTER_FRAGMENTS[room.REGISTER_FOCUSED]


def test_capabilities_build_register_fragment():
    import capabilities
    r = capabilities.build([], register="focused")
    assert len(r["fragments"]) == 1
    assert "工作台" in r["fragments"][0]


def test_capabilities_build_register_at_front():
    import capabilities
    r = capabilities.build(["execution"], agent_id="executor", register="companion")
    assert "温柔" in r["fragments"][0]


def test_capabilities_build_no_register():
    import capabilities
    r = capabilities.build([], register=None)
    assert len(r["fragments"]) == 0
