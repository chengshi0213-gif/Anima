#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
task_registry.py — M12 内核2：异步任务注册表（本地 daemon，不上云）

定位：把"提交走人 + 断线重连看回放"做成一等公民。
  · 任务 = 主循环上存活的 asyncio.Task（不阻塞 WS 消息循环）。
  · 每个任务自带事件缓冲：worker.run(ws=task) 直接把 task 当 ws 用，
    task.send_json 既缓冲又转发给"当前 attach 的 ws"。
  · WS 断线重连 → task_attach → 换上新 ws + replay 缓冲事件，流不丢。
  · 状态(queued/running/done/error/cancelled) 落 SQLite（SESSIONS_DB 加表），
    task_list / 历史可查；进程重启后旧任务仍可列出（live 句柄不跨进程）。

设计纪律：纯增量。不改任何现有工具/能力；ws_manager 的 chat 行为保持不变
（chat = submit + 自动 attach），老前端零改动。
"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

# 每任务事件缓冲上限：够 replay 一段"看着她写代码"，又不至于爆内存。
_MAX_EVENTS = 2000


class Task:
    """一个后台任务。自身 quack 成 ws（有 async send_json），供 worker.run(ws=task)
    直接使用：既把事件缓冲下来（重连可回放），又转发给当前 attach 的 ws。"""

    def __init__(self, task_id: str, agent: str, session_id: str, message: str):
        self.task_id = task_id
        self.agent = agent
        self.session_id = session_id
        self.message = message
        self.status = "queued"            # queued|running|done|error|cancelled
        self.summary = ""
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.aio_task: asyncio.Task | None = None
        self.result: dict | None = None
        self.events: list[dict] = []       # 缓冲的流事件（供重连 replay）
        self.ws = None                     # 当前 attach 的 ws（可变；None=走人了）

    async def send_json(self, payload: dict):
        """作为 ws 传给 worker.run：先缓冲，再转发给当前 attach 的 ws。"""
        self.events.append(payload)
        if len(self.events) > _MAX_EVENTS:
            del self.events[: len(self.events) - _MAX_EVENTS]
        ws = self.ws
        if ws is not None:
            try:
                await ws.send_json(payload)
            except Exception:
                pass

    @property
    def running(self) -> bool:
        return self.aio_task is not None and not self.aio_task.done()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "agent": self.agent,
            "session_id": self.session_id, "status": self.status,
            "message": self.message[:200], "summary": self.summary[:500],
            "created_at": self.created_at, "updated_at": self.updated_at,
            "running": self.running,
        }


_COLS = "task_id,agent,session_id,status,message,summary,created_at,updated_at"


class TaskRegistry:
    """live 任务（内存）+ 状态历史（SQLite）。"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._tasks: dict[str, Task] = {}    # 进程内的 live 任务句柄
        self._seq = 0
        self._init_table()

    def _init_table(self):
        with self._lock:
            self.conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, agent TEXT, session_id TEXT,
                status TEXT, message TEXT, summary TEXT,
                created_at TEXT, updated_at TEXT)""")
            self.conn.commit()

    # ── 生命周期 ──
    def create(self, agent: str, session_id: str, message: str) -> Task:
        self._seq += 1
        task_id = f"{agent}-{int(time.time() * 1000)}-{self._seq}"
        task = Task(task_id, agent, session_id, message)
        self._tasks[task_id] = task
        self._persist(task)
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def set_status(self, task: Task, status: str, summary: str = ""):
        task.status = status
        if summary:
            task.summary = summary
        task.updated_at = datetime.now().isoformat()
        self._persist(task)

    def _persist(self, task: Task):
        with self._lock:
            self.conn.execute(
                f"INSERT OR REPLACE INTO tasks ({_COLS}) VALUES (?,?,?,?,?,?,?,?)",
                (task.task_id, task.agent, task.session_id, task.status,
                 task.message[:2000], task.summary[:2000],
                 task.created_at, task.updated_at))
            self.conn.commit()

    # ── attach / detach（断线重连）──
    def attach(self, task_id: str, ws) -> Task | None:
        task = self._tasks.get(task_id)
        if task is not None:
            task.ws = ws
        return task

    def detach(self, task_id: str):
        task = self._tasks.get(task_id)
        if task is not None:
            task.ws = None

    def detach_ws(self, ws):
        """某个 ws 关闭：把所有 attach 到它的 live 任务解绑，避免向死连接发送。"""
        for task in self._tasks.values():
            if task.ws is ws:
                task.ws = None

    async def replay(self, task_id: str, ws):
        """把缓冲事件回放给新 attach 的 ws（重连"拉回流"）。"""
        task = self._tasks.get(task_id)
        if task is None:
            return
        for ev in list(task.events):
            try:
                await ws.send_json(ev)
            except Exception:
                break

    # ── 取消 ──
    async def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.running:
            task.aio_task.cancel()
        self.set_status(task, "cancelled")
        return True

    # ── 查询（SQLite 历史 + live 标记）──
    def _row_to_dict(self, r) -> dict:
        live = self._tasks.get(r[0])
        return {
            "task_id": r[0], "agent": r[1], "session_id": r[2],
            "status": r[3], "message": (r[4] or "")[:200],
            "summary": (r[5] or "")[:500], "created_at": r[6], "updated_at": r[7],
            "running": bool(live and live.running),
        }

    def list(self, agent: str | None = None, limit: int = 50) -> list[dict]:
        with self._lock:
            if agent:
                rows = self.conn.execute(
                    f"SELECT {_COLS} FROM tasks WHERE agent=? ORDER BY created_at DESC LIMIT ?",
                    (agent, limit)).fetchall()
            else:
                rows = self.conn.execute(
                    f"SELECT {_COLS} FROM tasks ORDER BY created_at DESC LIMIT ?",
                    (limit,)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_record(self, task_id: str) -> dict | None:
        with self._lock:
            r = self.conn.execute(
                f"SELECT {_COLS} FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._row_to_dict(r) if r is not None else None

    # ── 测试钩子 ──
    def _reset(self):
        self._tasks.clear()
        self._seq = 0
        with self._lock:
            self.conn.execute("DELETE FROM tasks")
            self.conn.commit()


# ── 模块级共享单例（8 个 WorkerServer 共用一份，零改构造调用）──
_REGISTRY: TaskRegistry | None = None


def get_registry() -> TaskRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        from config import SESSIONS_DB
        _REGISTRY = TaskRegistry(SESSIONS_DB)
    return _REGISTRY
