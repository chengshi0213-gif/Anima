#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 (v1.3.1) Harness 自演化提案测试：分级 / 排序 / 阈值 / 报告。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness_evolution import analyze, format_report, Proposal


class _FakeMem:
    """带 .all() 的桩，模拟 FailureMemory / SolutionMemory。"""
    def __init__(self, data):
        self._data = data

    def all(self):
        return dict(self._data)


def _fails(**sigs):
    """sigs: sig -> count（其余字段补默认）。"""
    return _FakeMem({
        sig: {"count": c, "category": "verify:pytest",
              "summary": f"AssertionError in {sig}"}
        for sig, c in sigs.items()
    })


def _sols(**sigs):
    """sigs: sig -> (resolved_count, rounds_min)。"""
    return _FakeMem({
        sig: {"resolved_count": rc, "rounds_min": rm, "category": "verify:pytest"}
        for sig, (rc, rm) in sigs.items()
    })


# ── 分级 ──────────────────────────────────────────────────────────────────
def test_high_priority_for_unresolved_recurring():
    props = analyze(_fails(a=5), _sols(), min_count=3)
    assert len(props) == 1
    assert props[0].priority == "high"
    assert "tool" in props[0].lever or "middleware" in props[0].lever
    assert props[0].resolved_count == 0


def test_medium_priority_for_resolved_recurring():
    props = analyze(_fails(a=5), _sols(a=(2, 1)), min_count=3)
    assert len(props) == 1
    assert props[0].priority == "medium"
    assert props[0].resolved_count == 2
    assert "1 轮" in props[0].rationale   # 带出最快修复轮数


# ── 阈值 ──────────────────────────────────────────────────────────────────
def test_below_threshold_excluded():
    props = analyze(_fails(a=2), _sols(), min_count=3)
    assert props == []


def test_threshold_boundary_inclusive():
    props = analyze(_fails(a=3), _sols(), min_count=3)
    assert len(props) == 1   # 恰好等于阈值 → 入选


# ── 排序：高优先在前；同级按撞击次数降序 ────────────────────────────────────
def test_sort_high_before_medium():
    # a: 高频已解（medium）；b: 高频未解（high）。high 应排在前
    props = analyze(_fails(a=10, b=4), _sols(a=(3, 2)), min_count=3)
    assert props[0].signature == "b"
    assert props[0].priority == "high"
    assert props[1].priority == "medium"


def test_sort_same_priority_by_count_desc():
    props = analyze(_fails(a=4, b=9), _sols(), min_count=3)
    assert [p.signature for p in props] == ["b", "a"]   # 撞得多的在前


# ── 报告 ──────────────────────────────────────────────────────────────────
def test_report_empty_when_no_proposals():
    report = format_report([], fail_total=1, sol_total=0, min_count=3)
    assert "暂无" in report
    assert "别为保险堆功能" in report


def test_report_table_lists_proposals():
    props = analyze(_fails(a=5), _sols(), min_count=3)
    report = format_report(props, fail_total=1, sol_total=0, min_count=3)
    assert "Harness 自演化提案" in report
    assert "🔴 高" in report
    assert "arXiv:2604.25850" in report


def test_proposal_to_dict_roundtrips():
    p = Proposal("sig", "verify:pytest", 5, 0, "high", "tool/middleware", "why")
    d = p.to_dict()
    assert d["failure_count"] == 5
    assert d["priority"] == "high"
