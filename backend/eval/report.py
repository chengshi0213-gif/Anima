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
    """✅通过 / ❌跑了没过 / ⚠配置坑 / 🌐网络抖 / ⏭跳过 / 💥崩溃。"""
    if r.error_kind == "setup":
        return "⚠"
    if r.error_kind == "transient":
        return "🌐"
    if r.error_kind == "skipped":
        return "⏭"
    if r.error_kind == "crash":
        return "💥"
    return "✅" if r.passed else "❌"


def _unreliable_banner(suite: SuiteResult) -> list[str]:
    """基线不可信时的醒目警告块（环境/配置错误把题挡在门外，不是模型能力问题）。"""
    if suite.reliable:
        return []
    out = [
        f"> ⚠️ **此基线不可信**：{suite.not_attempted}/{suite.total} 题因环境/配置错误未能起跑"
        f"（不是模型能力问题，下面的完成率不能当基线）。修复后重跑才作数。",
    ]
    reasons = suite.setup_reasons()
    if reasons:
        out.append(">")
        out.append("> 需先修复：")
        out.extend(f"> - {r}" for r in reasons)
    out.append("")
    return out


def format_report(suite: SuiteResult) -> str:
    """单次跑的 markdown 报告。"""
    lines = [
        f"# 评估报告 — {suite.model}" + (f"（{suite.label}）" if suite.label else ""),
        "",
    ]
    lines += _unreliable_banner(suite)
    rate_line = f"**自主完成率：{_pct(suite.completion_rate)}**　（{suite.passed}/{suite.total} 通过）"
    if suite.not_attempted > 0:
        rate_line += (f"\n**真实能力完成率：{_pct(suite.attempted_rate)}**"
                      f"　（{suite.passed}/{suite.attempted_count} 起跑题通过，"
                      f"{suite.not_attempted} 题因网络/配置未起跑，已排除）")
    lines += [
        rate_line,
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
    noisy = not a.reliable or not b.reliable
    if noisy:
        delta = b.attempted_rate - a.attempted_rate
        rate_fn = lambda s: s.attempted_rate
        rate_label = "真实能力完成率"
    else:
        delta = b.completion_rate - a.completion_rate
        rate_fn = lambda s: s.completion_rate
        rate_label = "完成率"
    sign = "＋" if delta >= 0 else "－"
    lines = [
        f"# 对比报告　{label_a} → {label_b}",
        "",
    ]
    if noisy:
        bad = ", ".join(lbl for lbl, s in ((label_a, a), (label_b, b)) if not s.reliable)
        lines += [
            f"> ⚠️ **{bad} 侧有网络/配置错误**，部分题未起跑。下面用「真实能力完成率」"
            f"（仅算起跑题）做对比——比原始完成率更准，但最可靠的做法仍是网络稳定后重跑。",
            "",
        ]
    lines += [
        f"- {label_a}（{a.model}）：{_pct(rate_fn(a))}　（{a.passed}/{a.attempted_count if noisy else a.total}）",
        f"- {label_b}（{b.model}）：{_pct(rate_fn(b))}　（{b.passed}/{b.attempted_count if noisy else b.total}）",
        f"- **{rate_label}变化：{sign}{_pct(abs(delta))}**",
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
