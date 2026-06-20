#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
divination_history.py — 排盘历史存档（M6 灵魂空间 ·「我的命盘」）

本地 JSON 文件持久化每次排盘结果（出生信息快照 + 排好版命盘 markdown + 时间），
供「我的命盘」室回看历次解读。纯本地文件，绝不联网。
"""
import json
import time
import uuid
from pathlib import Path
from typing import Optional

_HISTORY_FILE = Path.home() / ".anima" / "data" / "divination_history.json"
MAX_RECORDS = 50


def _load() -> list[dict]:
    try:
        if _HISTORY_FILE.exists():
            data = json.loads(_HISTORY_FILE.read_text("utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save(records: list[dict]) -> None:
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), "utf-8")


def list_history(limit: int = 20) -> list[dict]:
    """最近的排盘记录在前。"""
    return _load()[:limit]


def add_record(birth: dict, markdown: str, time_unknown: bool = False) -> dict:
    """新增一条排盘记录；超过 MAX_RECORDS 自动淘汰最旧的。"""
    record = {
        "id": str(uuid.uuid4()),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "birth": birth,
        "markdown": markdown,
        "time_unknown": bool(time_unknown),
    }
    records = _load()
    records.insert(0, record)
    if len(records) > MAX_RECORDS:
        records = records[:MAX_RECORDS]
    _save(records)
    return record


def get_record(record_id: str) -> Optional[dict]:
    for r in _load():
        if r.get("id") == record_id:
            return r
    return None


def delete_record(record_id: str) -> bool:
    records = _load()
    remaining = [r for r in records if r.get("id") != record_id]
    if len(remaining) == len(records):
        return False
    _save(remaining)
    return True
