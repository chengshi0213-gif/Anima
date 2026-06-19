#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval.spec — 评估任务集 schema（声明式 yaml）

一个任务 = 一个自包含的微工作区：
  - setup.files：初始文件（含一个会失败的测试或一个待修的 bug）
  - prompt：交给 agent 的任务描述
  - verify：验收命令（exit 0 = 通过）。复用 verify_gate 的同一套验证哲学。

自包含微工作区（而非"clone 整个 Anima 仓库"）的好处：可复现、跑得快、
精确隔离被测的那一点，数字不被无关代码污染。代价是任务要自己造——
但"宁可少而真，不可多而水"（规划原话）。
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TASKS_DIR = Path(__file__).resolve().parent / "tasks"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


@dataclass
class EvalTask:
    """一道评估题。"""
    id: str
    prompt: str
    verify: str                              # 验收命令，exit 0 = 通过
    setup_files: dict[str, str] = field(default_factory=dict)  # 相对路径 → 内容
    title: str = ""
    category: str = "misc"                   # bug-fix / add-feature / fix-test / refactor / edge-case
    timeout: int = 120                       # 验收命令超时（秒）

    def __post_init__(self):
        if not self.id or not _ID_RE.match(self.id):
            raise ValueError(f"任务 id 非法（须小写字母数字连字符）: {self.id!r}")
        if not self.prompt.strip():
            raise ValueError(f"任务 {self.id} 缺 prompt")
        if not self.verify.strip():
            raise ValueError(f"任务 {self.id} 缺 verify 验收命令")
        if not self.title:
            self.title = self.id


def _coerce(raw: dict, source: str) -> EvalTask:
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: 任务必须是 mapping，得到 {type(raw).__name__}")
    setup = raw.get("setup") or {}
    files = setup.get("files") if isinstance(setup, dict) else None
    return EvalTask(
        id=str(raw.get("id", "")).strip(),
        prompt=str(raw.get("prompt", "")),
        verify=str(raw.get("verify", "")).strip(),
        setup_files={str(k): str(v) for k, v in (files or {}).items()},
        title=str(raw.get("title", "")).strip(),
        category=str(raw.get("category", "misc")).strip() or "misc",
        timeout=int(raw.get("timeout", 120)),
    )


def load_task(path: str | Path) -> EvalTask:
    """加载单个任务 yaml。"""
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return _coerce(raw, p.name)


def load_tasks(directory: str | Path | None = None) -> list[EvalTask]:
    """加载目录下所有 *.yaml / *.yml 任务，按 id 排序；id 重复则报错。"""
    d = Path(directory) if directory else TASKS_DIR
    if not d.exists():
        return []
    tasks: list[EvalTask] = []
    seen: set[str] = set()
    for p in sorted([*d.glob("*.yaml"), *d.glob("*.yml")]):
        t = load_task(p)
        if t.id in seen:
            raise ValueError(f"任务 id 重复: {t.id}（{p.name}）")
        seen.add(t.id)
        tasks.append(t)
    return sorted(tasks, key=lambda t: t.id)
