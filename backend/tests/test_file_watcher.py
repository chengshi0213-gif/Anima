#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_file_watcher.py — FileWatcherManager._on_event dict-result fix

锁定：_on_event 在 _run_fn 返回 dict 时通过 result_to_text 转为字符串，
      不再对 dict 做 [:1000] 切片（原先会抛 TypeError）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import file_watcher as fw_mod  # noqa: E402
from file_watcher import FileWatcherManager  # noqa: E402


@pytest.fixture
def watcher(tmp_path, monkeypatch):
    monkeypatch.setattr(fw_mod, "RULES_FILE", tmp_path / "rules.json")
    monkeypatch.setattr(fw_mod, "EVENTS_FILE", tmp_path / "events.json")
    w = FileWatcherManager()
    return w


def test_on_event_handles_dict_result(watcher, tmp_path):
    rule = {
        "id": "test01",
        "name": "测试规则",
        "agent": "shoucang",
        "prompt_template": "处理 {filename}",
        "trigger_count": 0,
    }
    watcher._rules[rule["id"]] = rule

    async def fake_run_fn(agent, prompt):
        return {"status": "completed", "summary": "done"}

    watcher.set_run_fn(fake_run_fn)

    asyncio.run(watcher._on_event(rule, str(tmp_path / "hello.txt"), "created"))

    assert len(watcher._events) == 1
    evt = watcher._events[0]
    assert evt["ok"] is True
    assert evt["output"] == "done"


def test_on_event_handles_string_result(watcher, tmp_path):
    rule = {
        "id": "test02",
        "name": "测试规则2",
        "agent": "shoucang",
        "prompt_template": "处理 {filename}",
        "trigger_count": 0,
    }
    watcher._rules[rule["id"]] = rule

    async def fake_run_fn(agent, prompt):
        return "直接字符串"

    watcher.set_run_fn(fake_run_fn)

    asyncio.run(watcher._on_event(rule, str(tmp_path / "hello.txt"), "created"))

    evt = watcher._events[0]
    assert evt["ok"] is True
    assert evt["output"] == "直接字符串"


def test_on_event_handles_run_fn_exception(watcher, tmp_path):
    rule = {
        "id": "test03",
        "name": "测试规则3",
        "agent": "shoucang",
        "prompt_template": "处理 {filename}",
        "trigger_count": 0,
    }
    watcher._rules[rule["id"]] = rule

    async def boom(agent, prompt):
        raise RuntimeError("炸了")

    watcher.set_run_fn(boom)

    asyncio.run(watcher._on_event(rule, str(tmp_path / "hello.txt"), "created"))

    evt = watcher._events[0]
    assert evt["ok"] is False
    assert "炸了" in evt["output"]
