#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval.report — 完成率报告 + 改动前后 / 模型 A vs B 对比

核心数永远是「自主完成率」。一切 harness 改动的真伪都由这张表裁决：
完成率没动 = 这个 Phase 没真起作用，回去查，而不是继续堆功能。
"""
from __future__ import annotations
import json
from pathlib import Path

from .runner import SuiteResult, TaskResult


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _mark(r: TaskResult) -> str:
    return "✅" if r.passed else "❌"


def format_report(suite: SuiteResult) -> str:
    """单次跑的 markdown 报告。"""
    lines = [
        f"# 评估报告 — {suite.model}" + (f"（{suite.label}）" if suite.label else ""),
        "",
        f"**自主完成率：{_pct(suite.completion_rate)}**　（{suite.passed}/{suite.total} 通过）",
        "",
        "| 题目 | 结果 | 退出码 | 轮数 | 耗时(s) | 备注 |",
        "|---|---|---|---|---|---|",
    ]
    for r in suite.results:
        note = r.error or (r.failure_summary.splitlines()[0] if r.failure_summary else r.status)
        lines.append(
            f"| {r.id} | {_mark(r)} | {r.exit_code} | {r.rounds} | {r.elapsed} | {note[:60]} |")
    return "\n".join(lines)


def format_compare(a: SuiteResult, b: SuiteResult,
                   label_a: str = "A", label_b: str = "B") -> str:
    """两次跑的对比（改动前后 / 模型 A vs B）。逐题列出变化，给出完成率差。"""
    by_id_a = {r.id: r for r in a.results}
    by_id_b = {r.id: r for r in b.results}
    all_ids = sorted(set(by_id_a) | set(by_id_b))
    delta = b.completion_rate - a.completion_rate
    sign = "＋" if delta >= 0 else "－"
    lines = [
        f"# 对比报告　{label_a} → {label_b}",
        "",
        f"- {label_a}（{a.model}）：{_pct(a.completion_rate)}　（{a.passed}/{a.total}）",
        f"- {label_b}（{b.model}）：{_pct(b.completion_rate)}　（{b.passed}/{b.total}）",
        f"- **完成率变化：{sign}{_pct(abs(delta))}**",
        "",
        f"| 题目 | {label_a} | {label_b} | 变化 |",
        "|---|---|---|---|",
    ]
    for tid in all_ids:
        ra, rb = by_id_a.get(tid), by_id_b.get(tid)
        ma = _mark(ra) if ra else "—"
        mb = _mark(rb) if rb else "—"
        if ra and rb and ra.passed != rb.passed:
            change = "🟢 修好了" if rb.passed else "🔴 改坏了"
        else:
            change = ""
        lines.append(f"| {tid} | {ma} | {mb} | {change} |")
    return "\n".join(lines)


def save_report(suite: SuiteResult, path: str | Path) -> Path:
    """落盘：同时存一份 markdown 和一份机读 json（同名 .json）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(format_report(suite), encoding="utf-8")
    p.with_suffix(".json").write_text(
        json.dumps(suite.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return p
