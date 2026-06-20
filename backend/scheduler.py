#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时任务调度器 — APScheduler 封装
支持 interval（每隔N分/时）和 cron（固定时间）两种触发器
任务执行结果写入日志，可通过 HTTP 查询
"""
import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from config import DATA_DIR

SCHED_DIR  = DATA_DIR / "scheduler"
TASKS_FILE = SCHED_DIR / "tasks.json"
LOGS_FILE  = SCHED_DIR / "run_logs.json"
SCHED_DIR.mkdir(parents=True, exist_ok=True)

MAX_LOGS = 200   # 最多保留的执行记录条数


def result_to_text(result) -> str:
    """把 _run_fn 的返回值摊平成可落日志的字符串。

    AgentBase.run() / run_daily_sop() 返回 dict（status/summary/error 等字段），
    旧的 file_watcher 风格回调可能直接返回字符串——两种都兼容。
    """
    if isinstance(result, dict):
        return str(result.get("summary") or result.get("error")
                   or result.get("status") or result)
    return str(result)


class TaskScheduler:
    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._tasks: dict[str, dict] = {}   # task_id → task_def
        self._logs:  list[dict]      = []   # 执行记录（内存 + 持久化）
        self._run_fn: Callable | None = None   # 注入：用于执行 agent

    # ── 初始化 ──────────────────────────────────────
    def set_run_fn(self, fn: Callable):
        """注入 agent 执行函数 async fn(agent_id, prompt) → str"""
        self._run_fn = fn

    def start(self):
        self._load()
        self._scheduler.start()
        # 恢复持久化的任务
        for task in self._tasks.values():
            if task.get("enabled", True):
                self._schedule_job(task)

    def stop(self):
        self._scheduler.shutdown(wait=False)

    # ── 持久化 ──────────────────────────────────────
    def _load(self):
        if TASKS_FILE.exists():
            self._tasks = json.loads(TASKS_FILE.read_text("utf-8"))
        if LOGS_FILE.exists():
            self._logs = json.loads(LOGS_FILE.read_text("utf-8"))

    def _save_tasks(self):
        TASKS_FILE.write_text(json.dumps(self._tasks, ensure_ascii=False, indent=2), "utf-8")

    def _save_logs(self):
        LOGS_FILE.write_text(json.dumps(self._logs[-MAX_LOGS:], ensure_ascii=False, indent=2), "utf-8")

    # ── 任务 CRUD ────────────────────────────────────
    def add_task(self, name: str, agent: str, prompt: str,
                 trigger_type: str, trigger_value: str) -> dict:
        """
        trigger_type: "interval" | "cron"
        trigger_value:
          interval → "30m" / "2h" / "1d"
          cron     → "HH:MM" (每天) 或 "* * * * *" (标准cron)
        """
        task_id = str(uuid.uuid4())[:8]
        task = {
            "id":            task_id,
            "name":          name,
            "agent":         agent,
            "prompt":        prompt,
            "trigger_type":  trigger_type,
            "trigger_value": trigger_value,
            "enabled":       True,
            "created":       datetime.now().isoformat(),
            "last_run":      None,
            "run_count":     0,
        }
        self._tasks[task_id] = task
        self._save_tasks()
        self._schedule_job(task)
        return task

    def add_task_if_missing(self, name: str, agent: str, prompt: str,
                            trigger_type: str, trigger_value: str) -> dict | None:
        """幂等注册系统任务：已存在同名任务则跳过，否则新建。

        供启动流程注册周期性系统任务（M2a 每日 SOP / M2b 每周升格 / M10
        偏好学习等）共用，避免每次重启重复注册。
        """
        if any(t["name"] == name for t in self._tasks.values()):
            return None
        return self.add_task(name, agent, prompt, trigger_type, trigger_value)

    def toggle_task(self, task_id: str) -> dict:
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "任务不存在"}
        task["enabled"] = not task["enabled"]
        self._save_tasks()
        if task["enabled"]:
            self._schedule_job(task)
        else:
            try:
                self._scheduler.remove_job(task_id)
            except Exception:
                pass
        return task

    def delete_task(self, task_id: str) -> bool:
        if task_id not in self._tasks:
            return False
        try:
            self._scheduler.remove_job(task_id)
        except Exception:
            pass
        del self._tasks[task_id]
        self._save_tasks()
        return True

    def list_tasks(self) -> list[dict]:
        return list(self._tasks.values())

    def list_logs(self, task_id: str | None = None, limit: int = 50) -> list[dict]:
        logs = self._logs if not task_id else [l for l in self._logs if l["task_id"] == task_id]
        return list(reversed(logs))[:limit]

    # ── 调度核心 ─────────────────────────────────────
    def _schedule_job(self, task: dict):
        trigger = self._make_trigger(task["trigger_type"], task["trigger_value"])
        if trigger is None:
            return
        try:
            self._scheduler.add_job(
                self._execute_task,
                trigger=trigger,
                id=task["id"],
                args=[task["id"]],
                replace_existing=True,
                misfire_grace_time=300,
            )
        except Exception as e:
            print(f"[Scheduler] 添加任务失败 {task['id']}: {e}")

    @staticmethod
    def _make_trigger(trigger_type: str, trigger_value: str):
        try:
            if trigger_type == "interval":
                val = trigger_value.strip().lower()
                if val.endswith("m"):
                    return IntervalTrigger(minutes=int(val[:-1]))
                elif val.endswith("h"):
                    return IntervalTrigger(hours=int(val[:-1]))
                elif val.endswith("d"):
                    return IntervalTrigger(days=int(val[:-1]))
                else:
                    return IntervalTrigger(minutes=int(val))
            elif trigger_type == "cron":
                val = trigger_value.strip()
                if ":" in val and len(val) <= 5:   # HH:MM
                    h, m = val.split(":")
                    return CronTrigger(hour=int(h), minute=int(m))
                else:                               # 标准 cron
                    parts = val.split()
                    if len(parts) == 5:
                        return CronTrigger(
                            minute=parts[0], hour=parts[1],
                            day=parts[2], month=parts[3], day_of_week=parts[4]
                        )
        except Exception as e:
            print(f"[Scheduler] 触发器解析失败 {trigger_type}/{trigger_value}: {e}")
        return None

    async def _execute_task(self, task_id: str):
        task = self._tasks.get(task_id)
        if not task or not task.get("enabled"):
            return

        started = datetime.now().isoformat()
        output, ok = "", True
        try:
            if self._run_fn:
                output = await self._run_fn(task["agent"], task["prompt"])
            else:
                output = "(run_fn 未注入)"
        except Exception as e:
            output = f"执行错误: {e}"
            ok = False

        task["last_run"]  = started
        task["run_count"] = task.get("run_count", 0) + 1
        self._save_tasks()

        log_entry = {
            "task_id":  task_id,
            "task_name": task["name"],
            "agent":    task["agent"],
            "started":  started,
            "output":   result_to_text(output)[:2000],
            "ok":       ok,
        }
        self._logs.append(log_entry)
        self._save_logs()
        print(f"[Scheduler] ✓ {task['name']} ({task['agent']}) 执行{'成功' if ok else '失败'}")


# 单例
scheduler = TaskScheduler()
