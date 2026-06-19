#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
failure_memory — 跨会话失败记忆（v1.3 Phase R）

命题（2026 harness 研究 + Fable 5 Memory Tool 复盘）：
  弱模型会在不同会话里反复撞同一类错误，却没有跨会话学习——每次都从零开始 thrash。
  给它一份"这个坑历史上出现过 N 次，当时的错误长这样"的记忆，至少能止住盲目重试。

本模块只做两件事，干净、可持久化、可测：
  1. error_signature(category, text)  把易变的错误文本归一化成稳定签名（同类错误同签名）
  2. FailureMemory                    JSON 落盘的 签名 → 频次/摘要 知识库，record / recall

归一化是关键：路径、行号、内存地址、十六进制都会变，但"AssertionError: 期望 X 得到 Y"
的结构是稳定的。归一化后同一类错误命中同一签名，跨会话累计。

接入点：verify_gate 自修复闭环（agent_base._run_verify_gate）——验证红时 record + recall，
历史命中就把"似曾相识"提示附进给模型的报错消息。不持久化解法（自动判定解法不可靠，
留待后续用 LLM 蒸馏 hindsight note 升级），只诚实记录"这类坑反复出现"。
"""
from __future__ import annotations
import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path


# ── 归一化：抹掉易变细节，保留错误结构 ────────────────────────────────────
_WIN_PATH = re.compile(r"[A-Za-z]:\\[^\s:*?\"<>|]+")       # C:\foo\bar.py
_NIX_PATH = re.compile(r"/(?:[\w.\-]+/)+[\w.\-]+")          # /foo/bar.py
_PYTEST_NODE = re.compile(r"::[\w\[\]\-.]+")               # ::test_x[param] 节点名
_HEXADDR = re.compile(r"0x[0-9a-fA-F]+")
_NUM = re.compile(r"\b\d+\b")
_WS = re.compile(r"\s+")

# 常见错误类型名——保留它们作为签名的强特征。
_ERRTYPE = re.compile(
    r"\b([A-Z][A-Za-z]*(?:Error|Exception|Warning)"
    r"|TS\d{3,5}"                       # TypeScript 错误码
    r"|E\d{3,4}"                        # flake8/pylint 码
    r"|panic|SIGSEGV|FAILED)\b")


def _normalize(text: str) -> str:
    """抹掉路径/地址/数字，压平空白，转小写——同类错误归一到同一串。"""
    if not text:
        return ""
    t = _WIN_PATH.sub("<path>", text)
    t = _NIX_PATH.sub("<path>", t)
    t = _PYTEST_NODE.sub("<node>", t)
    t = _HEXADDR.sub("<addr>", t)
    t = _NUM.sub("<n>", t)
    t = _WS.sub(" ", t).strip().lower()
    return t[:2000]


def error_signature(category: str, text: str) -> str:
    """生成稳定签名：category + 主要错误类型 + 归一化文本哈希。

    同一类错误（路径/行号/数字不同但结构相同）→ 同一签名，可跨会话累计。
    """
    norm = _normalize(text)
    types = _ERRTYPE.findall(text or "")
    type_tag = (types[0] if types else "generic").lower()
    digest = hashlib.md5(norm.encode("utf-8")).hexdigest()[:10]
    cat = (category or "general").strip().lower()
    return f"{cat}:{type_tag}:{digest}"


# ── 持久化知识库 ──────────────────────────────────────────────────────────
class FailureMemory:
    """签名 → {count, category, summary, first_seen, last_seen} 的 JSON 知识库。

    线程安全（M6 的 delegate 在独立线程跑子员工，可能并发写）。
    """

    def __init__(self, path: str | Path | None = None):
        if path is None:
            try:
                from config import DATA_DIR
                path = Path(DATA_DIR) / "failure_memory.json"
            except Exception:
                path = Path.home() / ".anima" / "data" / "failure_memory.json"
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

    def record(self, category: str, text: str, summary: str = "") -> str:
        """记一次失败，返回其签名。同签名累加次数，首次摘要保留。"""
        sig = error_signature(category, text)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            entry = self._data.get(sig)
            if entry is None:
                self._data[sig] = {
                    "count": 1, "category": category,
                    "summary": (summary or text)[:600],
                    "first_seen": now, "last_seen": now,
                }
            else:
                entry["count"] += 1
                entry["last_seen"] = now
            self._save()
        return sig

    def recall(self, category: str, text: str) -> dict | None:
        """查这类错误以前是否出现过。返回条目（含 count/summary）或 None。

        注意：recall 反映 record 之前的历史。调用方应先 recall 再 record，
        这样"第一次见"不会自己提示自己。
        """
        sig = error_signature(category, text)
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
_SINGLETON: FailureMemory | None = None


def get_failure_memory() -> FailureMemory:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = FailureMemory()
    return _SINGLETON


def format_recall_hint(entry: dict) -> str:
    """把历史命中条目格式化成给模型的提示，附在验证报错消息后。"""
    count = entry.get("count", 1)
    summary = (entry.get("summary") or "").strip()
    hint = (f"\n\n[失败记忆] 这类错误在历史会话里已出现过 {count} 次——不是新坑，"
            f"别用上次失败的同一招硬撞。")
    if summary:
        hint += f"\n首次记录的样子：\n```\n{summary[:400]}\n```"
    return hint
