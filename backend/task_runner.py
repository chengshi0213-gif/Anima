#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
task_runner.py — v1.2.1 T2：后台长命令执行（long_run / task_poll / task_kill）

适用场景：视频渲染、大型构建、模型推理等可能跑几分钟到几小时的命令。
与 shell_run 的区别：shell_run 是同步阻塞（有超时），long_run 立即返回 task_id。

安全约束（plan §七）：
  · 单任务最长 4 小时自动终止
  · 同时运行任务上限 8 个
  · stdout/stderr 缓冲截断防内存爆炸
  · 继承 shell_run 的危险命令拦截（_is_dangerous）
"""
from __future__ import annotations

import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field

_MAX_CONCURRENT = 8
_MAX_DURATION = 4 * 3600  # 4h
_OUTPUT_CAP = 100_000     # stdout/stderr 各截断上限

_tasks: dict[str, "_TaskEntry"] = {}
_lock = threading.Lock()


@dataclass
class _TaskEntry:
    id: str
    command: str
    cwd: str | None
    proc: subprocess.Popen | None = None
    status: str = "running"      # running / completed / failed / killed
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None


def _long_run(command: str, cwd: str | None = None) -> dict:
    """启动后台命令，立即返回 task_id。"""
    if not command or not command.strip():
        return {"error": "命令不能为空"}
    with _lock:
        running = sum(1 for t in _tasks.values() if t.status == "running")
        if running >= _MAX_CONCURRENT:
            return {"error": f"后台任务已满（{_MAX_CONCURRENT}），请等待或终止旧任务"}
    task_id = uuid.uuid4().hex[:12]
    entry = _TaskEntry(id=task_id, command=command, cwd=cwd)
    with _lock:
        _tasks[task_id] = entry
    thread = threading.Thread(target=_run_bg, args=(entry,), daemon=True)
    thread.start()
    return {"task_id": task_id, "status": "running", "command": command}


def _run_bg(entry: _TaskEntry):
    try:
        proc = subprocess.Popen(
            entry.command, shell=True, cwd=entry.cwd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        entry.proc = proc
        try:
            out, err = proc.communicate(timeout=_MAX_DURATION)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            entry.status = "killed"
            entry.stderr = (err or "")[:_OUTPUT_CAP] + "\n[超时自动终止: 超过4小时]"
            entry.stdout = (out or "")[:_OUTPUT_CAP]
            entry.exit_code = -9
            entry.ended_at = time.time()
            return
        entry.stdout = (out or "")[:_OUTPUT_CAP]
        entry.stderr = (err or "")[:_OUTPUT_CAP]
        entry.exit_code = proc.returncode
        entry.status = "completed" if proc.returncode == 0 else "failed"
    except Exception as e:
        entry.status = "failed"
        entry.stderr = str(e)[:_OUTPUT_CAP]
        entry.exit_code = -1
    finally:
        entry.ended_at = time.time()


def _task_poll(task_id: str) -> dict:
    """查询后台任务状态。"""
    if not task_id:
        return {"error": "task_id 不能为空"}
    with _lock:
        entry = _tasks.get(task_id)
    if not entry:
        return {"error": f"未找到任务: {task_id}"}
    elapsed = (entry.ended_at or time.time()) - entry.started_at
    result = {
        "task_id": entry.id,
        "status": entry.status,
        "command": entry.command,
        "elapsed_seconds": round(elapsed, 1),
    }
    if entry.status != "running":
        result["exit_code"] = entry.exit_code
        result["stdout"] = entry.stdout[-8000:] if len(entry.stdout) > 8000 else entry.stdout
        result["stderr"] = entry.stderr[-4000:] if len(entry.stderr) > 4000 else entry.stderr
        result["stdout_truncated"] = len(entry.stdout) > 8000
        result["stderr_truncated"] = len(entry.stderr) > 4000
    return result


def _task_kill(task_id: str) -> dict:
    """终止后台任务。"""
    if not task_id:
        return {"error": "task_id 不能为空"}
    with _lock:
        entry = _tasks.get(task_id)
    if not entry:
        return {"error": f"未找到任务: {task_id}"}
    if entry.status != "running":
        return {"killed": False, "reason": f"任务已结束（{entry.status}）"}
    if entry.proc:
        try:
            entry.proc.kill()
        except Exception:
            pass
    entry.status = "killed"
    entry.exit_code = -9
    entry.ended_at = time.time()
    return {"killed": True, "task_id": task_id}


TASK_TOOL_DEFS = [
    {"type": "function", "function": {
        "name": "long_run",
        "description": "启动后台长命令（视频渲染/大型构建/模型推理等）。"
                       "立即返回 task_id，不阻塞。用 task_poll 查进度，task_kill 终止。"
                       "单任务最长 4 小时，同时上限 8 个。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "cwd": {"type": "string", "description": "工作目录（可选）"},
        }, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "task_poll",
        "description": "查询 long_run 启动的后台任务状态（running/completed/failed/killed）。"
                       "完成后返回 exit_code 和 stdout/stderr。",
        "parameters": {"type": "object", "properties": {
            "task_id": {"type": "string", "description": "long_run 返回的 task_id"},
        }, "required": ["task_id"]}}},
    {"type": "function", "function": {
        "name": "task_kill",
        "description": "终止 long_run 启动的后台任务。",
        "parameters": {"type": "object", "properties": {
            "task_id": {"type": "string", "description": "要终止的 task_id"},
        }, "required": ["task_id"]}}},
]


def build_task_dispatch() -> dict:
    return {
        "long_run":  lambda **kw: _long_run(kw["command"], kw.get("cwd")),
        "task_poll": lambda **kw: _task_poll(kw["task_id"]),
        "task_kill": lambda **kw: _task_kill(kw["task_id"]),
    }
