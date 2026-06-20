#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval.ablation_demo — Verify 闸门消融的「离线判别力自检」（v1.3.1 Phase P1）

背景：v1.3 的核心论点是「厚 harness（尤其 Verify 闸门）让弱模型变强」。要证伪/证真，
得用 `format_compare(gate_off, gate_on)` 的完成率差。但首跑真实基线（DeepSeek-V4-Pro）在
种子题上 100% 饱和——尺子量不出差，分不清是"闸门没用"还是"题太简单/基线太强"。

本模块解耦这个问题：用一个**确定性的"弱模型"桩**跑消融对照，证明**尺子本身有判别力**——
  · gate-off：模拟弱模型"没测就收工"——什么都不改，工作区留红 → 验收不过。
  · gate-on ：模拟 Verify 闸门把红验证回灌、逼自修复到绿——等价于套上参考解 → 验收通过。
两轮跑同一套真实种子题、用真实 `run_task`/`grade`（真跑 pytest），唯一被打桩的是"模型行为"。

结论：若 gate-on 完成率显著高于 gate-off，说明消融管道**能量出 Verify 闸门的增益**——
尺子是好的。这不是模型基准（桩不是真模型），真实数字仍需本机：
    python -m eval --model DeepSeek-V4-Pro                 # gate-on 基线
    python -m eval --model DeepSeek-V4-Pro --no-verify-gate  # gate-off 基线
本演示只回答"尺子能不能量出来"，不回答"某个真模型量出来多少"。
"""
from __future__ import annotations
import asyncio
from pathlib import Path

from .runner import run_task, apply_solution, SuiteResult
from .spec import EvalTask, load_tasks
from .report import format_compare


def winnable_tasks(limit: int = 2) -> list[EvalTask]:
    """挑带参考解的种子题（已被纪律闸门保证「初始红 / 套解绿」），取前 limit 道。
    取 2 道即可演示判别力，跑得快；要全量自己加大 limit。"""
    return [t for t in load_tasks() if t.solution_files][:limit]


def _stub_solver(task: EvalTask, *, verify_gate: bool):
    """确定性"弱模型"桩。唯一变量是 verify_gate：
      关 → 什么都不改（没测就收工），留红；
      开 → 套参考解（闸门逼自修复到绿的等价结果）。"""
    async def _solve(prompt: str, workspace: Path, model):
        if verify_gate:
            apply_solution(task, Path(workspace))
            return {"status": "verified", "turn_count": 3}
        return {"status": "completed", "turn_count": 1}
    return _solve


async def run_ablation_demo(tasks: list[EvalTask] | None = None
                            ) -> tuple[SuiteResult, SuiteResult]:
    """跑 gate-off / gate-on 两轮，返回 (off_suite, on_suite)。"""
    tasks = tasks if tasks is not None else winnable_tasks()
    off = SuiteResult(model="stub-weak-model", label="gate-off · 没测就收工")
    on = SuiteResult(model="stub-weak-model", label="gate-on · 闸门逼到绿")
    for t in tasks:
        off.results.append(await run_task(t, _stub_solver(t, verify_gate=False)))
        on.results.append(await run_task(t, _stub_solver(t, verify_gate=True)))
    return off, on


_PREAMBLE = (
    "# Verify 闸门消融 · 离线判别力自检\n\n"
    "> 这是 **apparatus self-test（尺子自检）**，不是模型基准。用确定性「弱模型」桩跑消融对照，\n"
    "> 证明消融管道能量出 Verify 闸门的增益。真实数字需本机烧额度跑：\n"
    "> `python -m eval --model DeepSeek-V4-Pro`（开）/ `--no-verify-gate`（关）。\n\n"
    "- **gate-off**：弱模型没测就收工（什么都不改）→ 留红\n"
    "- **gate-on**：Verify 闸门逼自修复到绿（等价套参考解）→ 转绿\n\n"
)


def main(save: bool = True) -> str:
    off, on = asyncio.run(run_ablation_demo())
    body = format_compare(off, on, label_a="gate-off", label_b="gate-on")
    full = _PREAMBLE + body + "\n"
    if save:
        out = Path(__file__).resolve().parents[2] / "docs" / "eval-ablation-demo.md"
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(full, encoding="utf-8")
        except Exception:
            pass
    return full


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(main())
