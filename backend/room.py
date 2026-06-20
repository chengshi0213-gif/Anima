#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
room.py — 房间感知（D8, v1.2.2）

"一人格·两房间·一引擎"：房间是派生状态（由 work_dir 决定），
不是用户要选的设置项。

  - daily     日常房间  → XiWorker（陪伴语气，companion register）
  - workspace 工作房间  → ExecutorWorker（简洁直接，focused register）
                        is_repo=True 时额外激活 git 专精
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import memory_injector as mi

ROOM_DAILY = "daily"
ROOM_WORK = "work"

REGISTER_COMPANION = "companion"
REGISTER_FOCUSED = "focused"

REGISTER_FRAGMENTS = {
    REGISTER_COMPANION: (
        "## 此刻的你\n"
        "你在陪她——温柔、体贴，可以聊心事、给情绪价值，"
        "语气自然放松，不必结论先行。\n"
    ),
    REGISTER_FOCUSED: (
        "## 此刻的你\n"
        "你在工作台——还是同一个\"她\"，但此刻收起闲聊，结论先行、简洁直接，"
        "像信任的同事并肩干活。改完报结果，不啰嗦，不主动找话题。\n"
    ),
}


@dataclass
class RoomConfig:
    room: str               # "daily" | "work"
    is_repo: bool
    register: str           # "companion" | "focused"
    worker_cls: str         # "XiWorker" | "ExecutorWorker"
    default_effort: str     # "quick" | "normal" | "deep"

    @property
    def register_fragment(self) -> str:
        return REGISTER_FRAGMENTS.get(self.register, "")


def _is_git_repo_quick(work_dir: str) -> bool:
    """快速判断是否在 git 仓库内（仅看 .git 目录是否存在，不启动 git 进程）。"""
    try:
        d = Path(work_dir)
        while d != d.parent:
            if (d / ".git").exists():
                return True
            d = d.parent
        return False
    except Exception:
        return False


def resolve_room(work_dir: str | None) -> RoomConfig:
    """根据 work_dir 推导房间配置。前端每次发消息带上当前 work_dir，
    未挂工作目录传 None/空字符串，即日常房间。"""
    if not work_dir or not work_dir.strip():
        return RoomConfig(ROOM_DAILY, False, REGISTER_COMPANION, "XiWorker", "normal")
    work_dir = work_dir.strip()
    is_repo = _is_git_repo_quick(work_dir)
    return RoomConfig(
        room=ROOM_WORK,
        is_repo=is_repo,
        register=REGISTER_FOCUSED,
        worker_cls="ExecutorWorker",
        default_effort="normal",
    )


def get_room_type() -> str:
    """当前房间类型：绑定了活跃项目 → "work"（工作房间），否则 "daily"（日常房间）。"""
    return ROOM_WORK if mi.get_active_project() else ROOM_DAILY


def is_work_room() -> bool:
    return get_room_type() == ROOM_WORK
