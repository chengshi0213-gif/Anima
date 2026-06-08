#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_task_registry.py — M12 内核2 任务注册表单元测试。

锁定的不变量：
  · create 持久化进 SQLite，get 返回 live 句柄。
  · Task.send_json：缓冲事件 + 转发给当前 attach 的 ws；ws=None 时只缓冲不报错。
  · attach / detach / detach_ws：换/解当前 ws。
  · replay：把缓冲事件按序回放给新 ws（断线重连拉回流）。
  · cancel：取消 live asyncio.Task 并落 cancelled 状态。
  · set_status：状态/摘要落库，list/get_record 读得到。
  · list：按 agent 过滤；running 标记反映 live 句柄。
  · _MAX_EVENTS：缓冲超限丢最旧、留最新。

运行:
    cd E:\\AI\\workspace\\Anima\\backend
    python -m pytest tests/test_task_registry.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import task_registry as tr  # noqa: E402
from task_registry import TaskRegistry, Task  # noqa: E402


class _FakeWS:
    """记录收到的 send_json；可设 fail=True 模拟死连接。"""
    def __init__(self, fail=False):
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, payload):
        if self.fail:
            raise ConnectionResetError("ws dead")
        self.sent.append(payload)


@pytest.fixture
def reg(tmp_path):
    return TaskRegistry(tmp_path / "tasks.db")


# ── create / get / 持久化 ──
def test_create_persists_and_get_returns_live(reg):
    t = reg.create("xi", "sess-1", "写个脚本")
    assert reg.get(t.task_id) is t
    rec = reg.get_record(t.task_id)
    assert rec["agent"] == "xi" and rec["session_id"] == "sess-1"
    assert rec["status"] == "queued" and rec["message"] == "写个脚本"


def test_task_ids_unique(reg):
    ids = {reg.create("xi", "s", "m").task_id for _ in range(5)}
    assert len(ids) == 5


# ── Task.send_json：缓冲 + 转发 ──
def test_send_json_buffers_and_forwards():
    t = Task("id1", "xi", "s", "m")
    ws = _FakeWS()
    t.ws = ws
    asyncio.run(t.send_json({"type": "assistant_delta", "data": {"content": "你"}}))
    asyncio.run(t.send_json({"type": "assistant_delta", "data": {"content": "好"}}))
    assert len(t.events) == 2                      # 缓冲
    assert len(ws.sent) == 2                       # 转发
    assert ws.sent[0]["data"]["content"] == "你"


def test_send_json_no_ws_only_buffers():
    t = Task("id1", "xi", "s", "m")
    asyncio.run(t.send_json({"type": "x"}))         # ws=None 不应抛
    assert t.events == [{"type": "x"}]


def test_send_json_dead_ws_does_not_raise():
    t = Task("id1", "xi", "s", "m")
    t.ws = _FakeWS(fail=True)
    asyncio.run(t.send_json({"type": "x"}))         # 死连接吞掉异常
    assert t.events == [{"type": "x"}]              # 仍缓冲


def test_max_events_cap_keeps_latest():
    t = Task("id1", "xi", "s", "m")
    n = tr._MAX_EVENTS + 50
    for i in range(n):
        asyncio.run(t.send_json({"i": i}))
    assert len(t.events) == tr._MAX_EVENTS
    assert t.events[-1] == {"i": n - 1}            # 留最新
    assert t.events[0] == {"i": n - tr._MAX_EVENTS}  # 丢最旧


# ── attach / detach ──
def test_attach_detach(reg):
    t = reg.create("xi", "s", "m")
    ws = _FakeWS()
    assert reg.attach(t.task_id, ws) is t and t.ws is ws
    reg.detach(t.task_id)
    assert t.ws is None


def test_detach_ws_unbinds_matching(reg):
    a = reg.create("xi", "s", "m"); b = reg.create("xi", "s2", "m2")
    ws = _FakeWS(); other = _FakeWS()
    reg.attach(a.task_id, ws); reg.attach(b.task_id, other)
    reg.detach_ws(ws)
    assert a.ws is None and b.ws is other          # 只解绑匹配的


def test_attach_unknown_returns_none(reg):
    assert reg.attach("nope", _FakeWS()) is None


# ── replay：断线重连拉回流 ──
def test_replay_sends_buffered_in_order(reg):
    t = reg.create("xi", "s", "m")
    for i in range(3):
        asyncio.run(t.send_json({"i": i}))         # 缓冲（无 ws）
    ws2 = _FakeWS()
    asyncio.run(reg.replay(t.task_id, ws2))
    assert [e["i"] for e in ws2.sent] == [0, 1, 2]


def test_replay_unknown_noop(reg):
    asyncio.run(reg.replay("nope", _FakeWS()))     # 不抛即通过


# ── set_status / list / get_record ──
def test_set_status_persists(reg):
    t = reg.create("xi", "s", "m")
    reg.set_status(t, "done", "完成啦")
    rec = reg.get_record(t.task_id)
    assert rec["status"] == "done" and rec["summary"] == "完成啦"


def test_list_filters_by_agent(reg):
    reg.create("xi", "s", "m1")
    reg.create("executor", "s", "m2")
    xi_tasks = reg.list(agent="xi")
    assert len(xi_tasks) == 1 and xi_tasks[0]["agent"] == "xi"
    assert len(reg.list()) == 2


def test_get_record_missing(reg):
    assert reg.get_record("nope") is None


# ── cancel ──
def test_cancel_unknown_false(reg):
    assert asyncio.run(reg.cancel("nope")) is False


def test_cancel_running_task_sets_cancelled(reg):
    async def _scenario():
        t = reg.create("xi", "s", "m")

        async def _long():
            await asyncio.sleep(10)

        t.aio_task = asyncio.create_task(_long())
        await asyncio.sleep(0)                      # 让任务真正起来
        assert t.running
        ok = await reg.cancel(t.task_id)
        assert ok is True
        # 等取消落地
        with pytest.raises(asyncio.CancelledError):
            await t.aio_task
        assert t.status == "cancelled"
        assert reg.get_record(t.task_id)["status"] == "cancelled"

    asyncio.run(_scenario())


def test_running_flag_reflects_live(reg):
    async def _scenario():
        t = reg.create("xi", "s", "m")
        assert reg.get_record(t.task_id)["running"] is False
        done = asyncio.create_task(asyncio.sleep(0))
        t.aio_task = done
        await done
        assert reg.get_record(t.task_id)["running"] is False

    asyncio.run(_scenario())


# ── 单例 ──
def test_get_registry_singleton(monkeypatch, tmp_path):
    monkeypatch.setattr(tr, "_REGISTRY", None)
    import config
    monkeypatch.setattr(config, "SESSIONS_DB", tmp_path / "singleton.db", raising=False)
    r1 = tr.get_registry()
    r2 = tr.get_registry()
    assert r1 is r2
