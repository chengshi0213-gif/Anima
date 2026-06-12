#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件监视器 — watchdog 封装
监听目录变动 → 触发 Agent 任务
支持 created / modified / deleted 事件过滤
"""
import asyncio
import fnmatch
import json
import uuid
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from config import DATA_DIR
from scheduler import result_to_text

WATCH_DIR  = DATA_DIR / "watcher"
RULES_FILE = WATCH_DIR / "rules.json"
EVENTS_FILE= WATCH_DIR / "events.json"
WATCH_DIR.mkdir(parents=True, exist_ok=True)

MAX_EVENTS = 300


class _Handler(FileSystemEventHandler):
    def __init__(self, rule: dict, callback: Callable):
        self.rule     = rule
        self.callback = callback
        self._loop    = asyncio.get_event_loop()

    def _match(self, path: str) -> bool:
        pat = self.rule.get("pattern", "*")
        return fnmatch.fnmatch(Path(path).name, pat)

    def _fire(self, event: FileSystemEvent):
        evt_type = event.event_type          # created / modified / deleted
        allowed  = self.rule.get("events", ["created","modified"])
        if evt_type not in allowed:
            return
        if not self._match(event.src_path):
            return
        asyncio.run_coroutine_threadsafe(
            self.callback(self.rule, event.src_path, evt_type),
            self._loop,
        )

    def on_created (self, e): self._fire(e)
    def on_modified(self, e): self._fire(e)
    def on_deleted (self, e): self._fire(e)


class FileWatcherManager:
    def __init__(self):
        self._rules:    dict[str, dict] = {}
        self._observer: Observer        = Observer()
        self._watches:  dict[str, any]  = {}   # rule_id → watchdog watch handle
        self._events:   list[dict]      = []
        self._run_fn:   Callable | None = None
        self._load()

    def set_run_fn(self, fn: Callable):
        self._run_fn = fn

    def start(self):
        self._observer.start()
        for rule in self._rules.values():
            if rule.get("enabled", True):
                self._watch_rule(rule)

    def stop(self):
        self._observer.stop()
        self._observer.join()

    # ── 持久化 ──────────────────────────────────────
    def _load(self):
        if RULES_FILE.exists():
            self._rules = json.loads(RULES_FILE.read_text("utf-8"))
        if EVENTS_FILE.exists():
            self._events = json.loads(EVENTS_FILE.read_text("utf-8"))

    def _save_rules(self):
        RULES_FILE.write_text(json.dumps(self._rules, ensure_ascii=False, indent=2), "utf-8")

    def _save_events(self):
        EVENTS_FILE.write_text(json.dumps(self._events[-MAX_EVENTS:], ensure_ascii=False, indent=2), "utf-8")

    # ── 规则 CRUD ────────────────────────────────────
    def add_rule(self, name: str, watch_path: str, pattern: str,
                 events: list, agent: str, prompt_template: str) -> dict:
        """
        prompt_template 可含 {path} {event} {filename} 占位符
        """
        rule_id = str(uuid.uuid4())[:8]
        rule = {
            "id":              rule_id,
            "name":            name,
            "watch_path":      watch_path,
            "pattern":         pattern,      # e.g. "*.py", "*.md", "*"
            "events":          events,       # ["created","modified","deleted"]
            "agent":           agent,
            "prompt_template": prompt_template,
            "enabled":         True,
            "created":         datetime.now().isoformat(),
            "trigger_count":   0,
        }
        self._rules[rule_id] = rule
        self._save_rules()
        self._watch_rule(rule)
        return rule

    def toggle_rule(self, rule_id: str) -> dict:
        rule = self._rules.get(rule_id)
        if not rule:
            return {"error": "规则不存在"}
        rule["enabled"] = not rule["enabled"]
        self._save_rules()
        if rule["enabled"]:
            self._watch_rule(rule)
        else:
            self._unwatch_rule(rule_id)
        return rule

    def delete_rule(self, rule_id: str) -> bool:
        if rule_id not in self._rules:
            return False
        self._unwatch_rule(rule_id)
        del self._rules[rule_id]
        self._save_rules()
        return True

    def list_rules(self) -> list[dict]:
        return list(self._rules.values())

    def list_events(self, rule_id: str | None = None, limit: int = 50) -> list[dict]:
        evts = self._events if not rule_id else [e for e in self._events if e["rule_id"] == rule_id]
        return list(reversed(evts))[:limit]

    # ── watchdog 管理 ────────────────────────────────
    def _watch_rule(self, rule: dict):
        rule_id    = rule["id"]
        watch_path = rule["watch_path"]
        if not Path(watch_path).exists():
            return   # 路径不存在，跳过

        self._unwatch_rule(rule_id)   # 先移除旧的
        handler = _Handler(rule, self._on_event)
        try:
            watch = self._observer.schedule(handler, watch_path, recursive=rule.get("recursive", False))
            self._watches[rule_id] = watch
        except Exception as e:
            print(f"[Watcher] 监听失败 {watch_path}: {e}")

    def _unwatch_rule(self, rule_id: str):
        watch = self._watches.pop(rule_id, None)
        if watch:
            try:
                self._observer.unschedule(watch)
            except Exception:
                pass

    async def _on_event(self, rule: dict, src_path: str, evt_type: str):
        p        = Path(src_path)
        prompt   = rule["prompt_template"].format(
            path=src_path, event=evt_type, filename=p.name, stem=p.stem
        )
        started  = datetime.now().isoformat()
        output, ok = "", True
        try:
            if self._run_fn:
                output = await self._run_fn(rule["agent"], prompt)
            else:
                output = "(run_fn 未注入)"
        except Exception as e:
            output, ok = f"执行错误: {e}", False

        rule["trigger_count"] = rule.get("trigger_count", 0) + 1
        self._save_rules()

        self._events.append({
            "rule_id":   rule["id"],
            "rule_name": rule["name"],
            "agent":     rule["agent"],
            "event":     evt_type,
            "path":      src_path,
            "started":   started,
            "output":    result_to_text(output)[:1000],
            "ok":        ok,
        })
        self._save_events()
        print(f"[Watcher] {evt_type} → {p.name} → {rule['agent']} {'✓' if ok else '✗'}")


# 单例
watcher = FileWatcherManager()
