#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval CLI — E4「跑基线」入口（python -m eval）

⚠️ 这一步会真正驱动 agent、烧 API 额度。框架本身（spec/runner/report）的正确性
由 tests/test_eval_spine.py 离线验证，无需 API。本 CLI 只在用户主动触发时花钱。

用法：
  python -m eval --model DeepSeek-V4-Pro --label baseline
  python -m eval --model Claude-Sonnet-4.6 --label claude-ref
  python -m eval --list                      # 只列任务，不跑
"""
from __future__ import annotations
import argparse, asyncio, sys
from datetime import datetime
from pathlib import Path

# 允许 `python -m eval` 从 backend 目录直接运行（top-level 模块在 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.spec import load_tasks                      # noqa: E402
from eval.runner import run_suite, make_executor_solver  # noqa: E402
from eval.report import format_report, save_report    # noqa: E402

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def main() -> int:
    ap = argparse.ArgumentParser(prog="eval", description="Anima 厚 harness 评估脊柱")
    ap.add_argument("--model", default=None, help="模型显示名（见 MODEL_REGISTRY），缺省用 agent 默认")
    ap.add_argument("--label", default="", help="本次跑的标签，如 baseline / with-verify-gate")
    ap.add_argument("--list", action="store_true", help="只列任务集，不执行")
    args = ap.parse_args()

    tasks = load_tasks()
    if not tasks:
        print("任务集为空（eval/tasks/ 下无 *.yaml）", file=sys.stderr)
        return 2

    if args.list:
        print(f"共 {len(tasks)} 道题：")
        for t in tasks:
            print(f"  - [{t.category}] {t.id} — {t.title}")
        return 0

    print(f"▶ 跑 {len(tasks)} 道题，模型={args.model or '(默认)'}，标签={args.label or '(无)'}")
    print("  这会驱动真实 agent 并消耗 API 额度…\n")
    solver = make_executor_solver()
    suite = asyncio.run(run_suite(tasks, solver, model=args.model, label=args.label))

    print(format_report(suite))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}_{args.label or 'run'}.md"
    path = save_report(suite, REPORTS_DIR / name)
    print(f"\n报告已存：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
