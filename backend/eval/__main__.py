#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval CLI — E4「跑基线」入口（python -m eval）

⚠️ 这一步会真正驱动 agent、烧 API 额度。框架本身（spec/runner/report）的正确性
由 tests/test_eval_spine.py 离线验证，无需 API。本 CLI 只在用户主动触发时花钱。

用法：
  python -m eval --model DeepSeek-V4-Pro --label baseline
  python -m eval --model DeepSeek-V4-Pro --no-verify-gate   # 消融：关 Verify 闸门
  python -m eval --model Claude-Sonnet-4.6 --label claude-ref
  python -m eval --list                      # 只列任务，不跑

消融跑法（量化 Verify 闸门对弱模型的增益）：
  python -m eval --model DeepSeek-V4-Pro --label gate-on
  python -m eval --model DeepSeek-V4-Pro --label gate-off --no-verify-gate
  两份报告的完成率差 = 闸门的真实贡献（可信前提：两份都 reliable）。
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
    ap.add_argument("--label", default="", help="本次跑的标签，如 baseline / gate-on / gate-off")
    ap.add_argument("--no-verify-gate", action="store_true",
                    help="消融：关闭 Verify 闸门（agent 声称完成即收工，不自动验证/自修复）")
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

    verify_gate = not args.no_verify_gate
    label = args.label or ("gate-off" if args.no_verify_gate else "")
    gate_note = "关" if args.no_verify_gate else "开"
    print(f"▶ 跑 {len(tasks)} 道题，模型={args.model or '(默认)'}，标签={label or '(无)'}，Verify闸门={gate_note}")
    print("  这会驱动真实 agent 并消耗 API 额度…\n")
    solver = make_executor_solver(verify_gate=verify_gate)
    suite = asyncio.run(run_suite(tasks, solver, model=args.model, label=label))

    print(format_report(suite))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}_{label or 'run'}.md"
    path = save_report(suite, REPORTS_DIR / name)
    print(f"\n报告已存：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
