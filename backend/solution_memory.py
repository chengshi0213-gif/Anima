#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
solution_memory — 跨会话解法记忆 / hindsight note（v1.3.1 Phase P3）

命题（承 failure_memory 的明确遗留）：
  失败记忆（Phase R）只诚实记录"这类坑反复出现过 N 次"，并在自己的文档里写明——
  "不持久化解法（自动判定解法不可靠，留待后续用 LLM 蒸馏 hindsight note 升级）"。
  本模块就是那次升级：当验证闸门**经自修复真的转绿**时，按同一套错误签名落一条
  "这类错误以前被解决过"的 hindsight note。

  对弱模型的价值是正向锚点：撞同类错误时，失败记忆给"别再用上次那招硬撞"（止损），
  解法记忆给"这坑以前 N 轮内修好过、是可解的"（止住过早放弃 / 谎称 unverified）。
  两者一负一正，夹住弱模型的 thrash。

设计与 failure_memory 严格对称、可持久化、离线可测：
  - 复用 failure_memory.error_signature —— 失败与解法用同一签名，才能配对召回。
  - 只在"闸门确认转绿"时 record_resolution（解法可信度由 verify_gate 背书，而非 LLM 猜测）。
  - note 是确定性结构摘要（修了几轮 + 解决的错误头），离线可测；
    预留 distill_fn 钩子，未来可接 LLM 把 note 蒸馏得更可迁移，不改接口。

接入点：agent_base._run_verify_gate —— 红时 recall 附正向提示；
        经修复转绿时 record_resolution。
"""
from __future__ import annotations
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from failure_memory import error_signature  # 失败与解法共用签名，才能配对


# ── 持久化知识库 ──────────────────────────────────────────────────────────
class SolutionMemory:
    """签名 → {resolved_count, category, note, rounds_min, rounds_last,
              first_resolved, last_resolved} 的 JSON 知识库。

    与 FailureMemory 同构：线程安全（delegate 子员工并发写）、坏档自愈、原子落盘。
    """

    def __init__(self, path: str | Path | None = None):
        if path is None:
            try:
                from config import DATA_DIR
                path = Path(DATA_DIR) / "solution_memory.json"
            except Exception:
                path = Path.home() / ".anima" / "data" / "solution_memory.json"
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            if self.path.is_file():
                return json.loads(self.path.read_text("utf-8"))
        except Exception:
            pass
        return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    def record_resolution(self, category: str, error_text: str, *,
                          note: str = "", repair_rounds: int = 0) -> str:
        """记一次"这类错误被解决了"，返回其签名（与失败记忆同签名）。

        同签名累加 resolved_count；记录最快/最近解决轮数；首条 note 保留
        （首次解法通常最干净，后续别覆盖）。"""
        sig = error_signature(category, error_text)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rounds = max(int(repair_rounds or 0), 0)
        with self._lock:
            entry = self._data.get(sig)
            if entry is None:
                self._data[sig] = {
                    "resolved_count": 1,
                    "category": category,
                    "note": (note or "")[:600],
                    "rounds_min": rounds,
                    "rounds_last": rounds,
                    "first_resolved": now,
                    "last_resolved": now,
                }
            else:
                entry["resolved_count"] += 1
                entry["rounds_last"] = rounds
                if rounds and (not entry.get("rounds_min") or rounds < entry["rounds_min"]):
                    entry["rounds_min"] = rounds
                entry["last_resolved"] = now
                if note and not entry.get("note"):
                    entry["note"] = note[:600]
            self._save()
        return sig

    def recall(self, category: str, error_text: str) -> dict | None:
        """查这类错误以前是否被解决过。返回条目（含 resolved_count/note）或 None。"""
        sig = error_signature(category, error_text)
        with self._lock:
            entry = self._data.get(sig)
            return dict(entry, signature=sig) if entry else None

    def recall_by_signature(self, sig: str) -> dict | None:
        with self._lock:
            entry = self._data.get(sig)
            return dict(entry, signature=sig) if entry else None

    def all(self) -> dict[str, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._data.items()}


# ── 进程级单例（接入 agent 用）────────────────────────────────────────────
_SINGLETON: SolutionMemory | None = None


def get_solution_memory() -> SolutionMemory:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = SolutionMemory()
    return _SINGLETON


def format_solution_hint(entry: dict) -> str:
    """把历史解法条目格式化成给模型的正向提示，附在验证报错消息后。"""
    n = entry.get("resolved_count", 1)
    rounds_min = entry.get("rounds_min") or 0
    note = (entry.get("note") or "").strip()
    hint = (f"\n\n[解法记忆] 好消息：这类错误以前被解决过 {n} 次——它是可解的，别急着标"
            f"未验证收工。")
    if rounds_min:
        hint += f"历史上最快 {rounds_min} 轮内修好。"
    if note:
        hint += f"\n当时是这么修好的：\n```\n{note[:400]}\n```"
    return hint
