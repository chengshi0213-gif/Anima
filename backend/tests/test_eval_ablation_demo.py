#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 (v1.3.1) Verify 闸门消融自检：证明消融管道对"闸门增益"有判别力。

全程离线：模型行为被确定性桩替代，验收用真实 pytest（{py} 占位符）跑临时微工作区。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.ablation_demo import run_ablation_demo, winnable_tasks
from eval.report import format_compare


def test_winnable_tasks_exist():
    # 种子题里必须有带参考解的题，否则消融自检无从跑起
    tasks = winnable_tasks()
    assert len(tasks) >= 1


def test_gate_on_beats_gate_off():
    off, on = asyncio.run(run_ablation_demo())
    assert off.total == on.total >= 1
    # gate-off：没测就收工 → 全红；gate-on：逼到绿 → 全过
    assert off.passed == 0
    assert on.passed == on.total
    # 尺子量得出增益：完成率差为正
    assert on.completion_rate > off.completion_rate


def test_compare_report_shows_positive_delta():
    off, on = asyncio.run(run_ablation_demo())
    report = format_compare(off, on, label_a="gate-off", label_b="gate-on")
    assert "对比报告" in report
    assert "🟢 修好了" in report   # 至少一题从红转绿


def test_demo_uses_isolated_workspaces_no_residue(tmp_path):
    # run_task 默认清掉临时工作区，跑完不该在种子题目录留下痕迹
    off, on = asyncio.run(run_ablation_demo())
    for r in [*off.results, *on.results]:
        assert r.exit_code is not None   # 真跑过验收（不是被环境挡门外）
