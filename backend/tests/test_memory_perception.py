#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_memory_perception.py — 记忆感知三式（M8）单元测试

覆盖：
  式③ 时间感：_relative_time() 分档（今天/昨天/N天前/N周前/N个月前/N年前），
       注入文本中"[相关记忆]"/"[重要提醒]"带相对时间括注，"[画像]"不带。
  式④ 主动想起：remind_at 字段端到端——schema 迁移、写入/读取 round-trip、
       due_reminders() 按 within_days 过滤、format_due_reminders() 文本格式。
  式⑤ 矛盾质疑：机制已由 M3 write_memory_gated 的 conflict 分支覆盖，
       这里只验证 remember 工具新增的 remind_at 透传与格式校验。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_memory_perception.py -v
"""
from __future__ import annotations

import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import capabilities  # noqa: E402
import memory_injector as mi  # noqa: E402
from memory_sqlite import SQLiteMemoryBackend  # noqa: E402


@pytest.fixture(autouse=True)
def sqlite_mem(tmp_path, monkeypatch):
    backend = SQLiteMemoryBackend(tmp_path / "mem.db")
    monkeypatch.setattr(mi, "_backend", backend)
    mi.invalidate_cache()
    mi.reset_session_writes()
    yield backend
    mi.invalidate_cache()
    mi.reset_session_writes()


def _ts(days_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days_ago * 86400))


def _backdate(backend: SQLiteMemoryBackend, key: str, days_ago: float):
    with backend._conn() as conn:
        conn.execute("UPDATE memories SET updated_at=? WHERE key=?", [_ts(days_ago), key])


# ── 式③ 时间感：_relative_time() ────────────────────────────────

def test_relative_time_buckets():
    assert mi._relative_time(_ts(0)) == "今天"
    assert mi._relative_time(_ts(1.5)) == "昨天"
    assert mi._relative_time(_ts(3.5)) == "3天前"
    assert mi._relative_time(_ts(10)) == "1周前"
    assert mi._relative_time(_ts(60)) == "2个月前"
    assert mi._relative_time(_ts(400)) == "1年前"


def test_relative_time_invalid_input_returns_empty():
    assert mi._relative_time("not-a-date") == ""
    assert mi._relative_time(None) == ""


def test_topic_layer_shows_relative_time_profile_does_not(sqlite_mem):
    sqlite_mem.write("称呼", "可以喊我阿狸", category="A", agent_id="xi", importance=5)
    sqlite_mem.write("下周行程", "周三去上海出差", category="C", agent_id="xi", importance=3)
    _backdate(sqlite_mem, "下周行程", 3.5)
    mi.invalidate_cache("xi")

    injection = mi.get_memory_injection("xi")

    profile_section = injection.split("[相关记忆]")[0]
    assert "称呼" in profile_section
    assert "称呼：可以喊我阿狸（" not in injection  # 画像层不带相对时间括注

    related_section = injection.split("[相关记忆]")[1]
    assert "下周行程：周三去上海出差（3天前）" in related_section


# ── 式④ 主动想起：remind_at schema 迁移 + round-trip ─────────────

def test_schema_migration_adds_remind_at_column(tmp_path):
    old_db = tmp_path / "old.db"
    conn = sqlite3.connect(str(old_db))
    conn.execute("""CREATE TABLE memories (
        id          TEXT PRIMARY KEY,
        agent_id    TEXT,
        category    TEXT NOT NULL DEFAULT 'general',
        key         TEXT NOT NULL,
        value       TEXT NOT NULL,
        importance  INTEGER NOT NULL DEFAULT 3,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )""")
    conn.execute(
        "INSERT INTO memories (id, agent_id, category, key, value, importance, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ["id1", "xi", "C", "旧记忆", "迁移前写入的", 3, "2026-01-01T00:00:00", "2026-01-01T00:00:00"],
    )
    conn.commit()
    conn.close()

    backend = SQLiteMemoryBackend(old_db)
    entries = backend.list_all("xi")
    assert entries[0].key == "旧记忆"
    assert entries[0].remind_at is None

    eid = backend.write("新记忆", "迁移后写入", category="C", agent_id="xi", remind_at="2026-06-12")
    entry = next(e for e in backend.list_all("xi") if e.id == eid)
    assert entry.remind_at == "2026-06-12"


def test_remind_at_roundtrip_via_write_and_list_all(sqlite_mem):
    sqlite_mem.write("评审日期", "下周二技术评审", category="C", agent_id="xi",
                     importance=4, remind_at="2026-06-15")
    sqlite_mem.write("普通备注", "随手记的事", category="C", agent_id="xi", importance=3)

    entries = {e.key: e for e in sqlite_mem.list_all("xi")}
    assert entries["评审日期"].remind_at == "2026-06-15"
    assert entries["普通备注"].remind_at is None


# ── 式④ 主动想起：due_reminders() / format_due_reminders() ──────

def test_due_reminders_filters_by_within_days(sqlite_mem):
    today = date.today()
    sqlite_mem.write("昨天到期", "已经过期但还没处理", category="C", agent_id="xi",
                     remind_at=(today - timedelta(days=1)).isoformat())
    sqlite_mem.write("今天到期", "今天的事", category="C", agent_id="xi",
                     remind_at=today.isoformat())
    sqlite_mem.write("明天到期", "明天的事", category="C", agent_id="xi",
                     remind_at=(today + timedelta(days=1)).isoformat())
    sqlite_mem.write("下周到期", "还早", category="C", agent_id="xi",
                     remind_at=(today + timedelta(days=7)).isoformat())
    sqlite_mem.write("全局提醒", "所有人格可见", category="C", agent_id=None,
                     remind_at=today.isoformat())

    due = sqlite_mem.due_reminders(agent_id="xi", within_days=1)
    keys = {e.key for e in due}
    assert keys == {"昨天到期", "今天到期", "明天到期", "全局提醒"}
    assert "下周到期" not in keys


def test_format_due_reminders_text_and_empty(sqlite_mem):
    today = date.today().isoformat()
    sqlite_mem.write("评审日期", "下周二技术评审", category="C", agent_id="xi",
                     importance=4, remind_at=today)
    mi.invalidate_cache("xi")

    text = mi.format_due_reminders("xi")
    assert "评审日期" in text
    assert "下周二技术评审" in text
    assert f"提醒日期：{today}" in text

    # 没有到期项时返回空串
    sqlite_mem.delete(next(e.id for e in sqlite_mem.list_all("xi") if e.key == "评审日期"))
    mi.invalidate_cache("xi")
    assert mi.format_due_reminders("xi") == ""


# ── remember 工具：remind_at 透传与格式校验 ──────────────────────

@pytest.fixture
def memory_dispatch():
    return capabilities.build(["memory"], agent_id="xi")


def test_remember_with_valid_remind_at_is_persisted(memory_dispatch):
    dispatch = memory_dispatch["dispatch"]
    r = dispatch["remember"](key="技术评审", value="下周二下午3点", category="C",
                             importance=4, remind_at="2026-06-15")
    assert r["ok"] is True

    entry = next(e for e in mi.list_memory("xi") if e.key == "技术评审")
    assert entry.remind_at == "2026-06-15"


def test_remember_with_invalid_remind_at_is_ignored(memory_dispatch):
    dispatch = memory_dispatch["dispatch"]
    r = dispatch["remember"](key="模糊日期", value="大概下个月吧", category="C",
                             importance=3, remind_at="下个月")
    assert r["ok"] is True

    entry = next(e for e in mi.list_memory("xi") if e.key == "模糊日期")
    assert entry.remind_at is None
