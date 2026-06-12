#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
room.py — 房间感知（D8 最小版）

"一人格·两房间·一引擎"（v1.2.2 §三 岔路口 #4）：房间是派生状态，
由是否绑定活跃项目（work_dir）决定，不是用户要选的设置项。

完整版 D8（register 联动 / ExecutorWorker 专精切换等）见 v1.2.2 规划；
这里只实现 M10「E 程序层偏好规则仅工作房间注入」所需的最小判断，
未来 D8 落地时在此基础上扩展，不冲突。
"""
from __future__ import annotations

import memory_injector as mi

ROOM_DAILY = "daily"
ROOM_WORK = "work"


def get_room_type() -> str:
    """当前房间类型：绑定了活跃项目 → "work"（工作房间），否则 "daily"（日常房间）。"""
    return ROOM_WORK if mi.get_active_project() else ROOM_DAILY


def is_work_room() -> bool:
    return get_room_type() == ROOM_WORK
