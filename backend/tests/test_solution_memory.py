#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 (v1.3.1) 解法记忆 / hindsight note 测试：
持久化知识库 + 与失败记忆签名配对 + 闸门转绿登记 / 红时正向召回。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from failure_memory import error_signature
from solution_memory import (
    SolutionMemory, get_solution_memory, format_solution_hint,
)
from agent_base import AgentBase


# ── SolutionMemory：record_resolution / recall / 持久化 ──────────────────────
def test_record_then_recall(tmp_path):
    sm = SolutionMemory(tmp_path / "sm.json")
    assert sm.recall("verify:pytest", "AssertionError: x") is None  # 首次无历史
    sm.record_resolution("verify:pytest", "AssertionError: x", repair_rounds=2)
    entry = sm.recall("verify:pytest", "AssertionError: x")
    assert entry is not None
    assert entry["resolved_count"] == 1
    assert entry["rounds_min"] == 2


def test_resolution_increments_count(tmp_path):
    sm = SolutionMemory(tmp_path / "sm.json")
    sm.record_resolution("v", "AssertionError: x at line 1", repair_rounds=3)
    sm.record_resolution("v", "AssertionError: x at line 2", repair_rounds=1)  # 归一后同签名
    entry = sm.recall("v", "AssertionError: x at line 3")
    assert entry["resolved_count"] == 2
    assert entry["rounds_min"] == 1   # 取历史最快
    assert entry["rounds_last"] == 1


def test_pairs_with_failure_signature(tmp_path):
    # 解法记忆必须与失败记忆用同一签名，才能在召回时配对
    cat, txt = "verify:pytest", "AssertionError: expected 1 got 2"
    sm = SolutionMemory(tmp_path / "sm.json")
    sig = sm.record_resolution(cat, txt)
    assert sig == error_signature(cat, txt)


def test_persistence_across_instances(tmp_path):
    p = tmp_path / "sm.json"
    sm1 = SolutionMemory(p)
    sm1.record_resolution("v", "ImportError at line 5: cannot import name", repair_rounds=2)
    sm2 = SolutionMemory(p)   # 新实例从磁盘加载
    entry = sm2.recall("v", "ImportError at line 9: cannot import name")  # 仅行号不同 → 同签名
    assert entry is not None
    assert entry["resolved_count"] == 1


def test_first_note_preserved(tmp_path):
    sm = SolutionMemory(tmp_path / "sm.json")
    sm.record_resolution("v", "AssertionError: expected 1", note="原始解法 original")
    sm.record_resolution("v", "AssertionError: expected 2", note="后来的解法 later")
    entry = sm.recall("v", "AssertionError: expected 3")
    assert "original" in entry["note"]   # 首条 note 保留，不被覆盖


def test_all_returns_copy(tmp_path):
    sm = SolutionMemory(tmp_path / "sm.json")
    sm.record_resolution("v", "X Error")
    snapshot = sm.all()
    snapshot.clear()
    assert len(sm.all()) == 1   # 改副本不影响内部


def test_corrupt_file_recovers(tmp_path):
    p = tmp_path / "sm.json"
    p.write_text("{not valid json", encoding="utf-8")
    sm = SolutionMemory(p)   # 不崩，当空库
    assert sm.all() == {}
    sm.record_resolution("v", "Y Error")
    assert len(sm.all()) == 1


# ── format_solution_hint ─────────────────────────────────────────────────
def test_format_solution_hint_is_positive():
    hint = format_solution_hint(
        {"resolved_count": 2, "rounds_min": 1, "note": "改了断言期望值"})
    assert "解法记忆" in hint
    assert "2" in hint           # 解决次数
    assert "可解" in hint         # 正向锚点
    assert "改了断言期望值" in hint


# ── 闸门接入：红时记 pending + 命中解法附正向提示；转绿登记解法 ─────────────
class _GateStub:
    max_repair_rounds = 3

    def _log(self, *a, **k):
        pass

    _run_verify_gate = AgentBase._run_verify_gate


def _make_failing_py(proj):
    (proj / "tests").mkdir(parents=True, exist_ok=True)
    (proj / "tests" / "test_s.py").write_text(
        "def test_bad():\n    assert 1 == 2\n", encoding="utf-8")


def _make_passing_py(proj):
    (proj / "tests" / "test_s.py").write_text(
        "def test_ok():\n    assert 1 == 1\n", encoding="utf-8")


def _isolate_memories(tmp_path, monkeypatch):
    import failure_memory as fmmod
    import solution_memory as smmod
    fm = fmmod.FailureMemory(tmp_path / "fm.json")
    sm = smmod.SolutionMemory(tmp_path / "sm.json")
    monkeypatch.setattr(fmmod, "_SINGLETON", fm)
    monkeypatch.setattr(smmod, "_SINGLETON", sm)
    return fm, sm


def test_gate_records_pending_on_red(tmp_path, monkeypatch):
    _isolate_memories(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    _make_failing_py(proj)

    stub = _GateStub()
    msgs = []
    action, _ = asyncio.run(stub._run_verify_gate(str(proj), 0, msgs, "s1"))
    assert action == "repair"
    # 红时应记下 pending（待转绿登记）
    assert stub._pending_resolution is not None
    assert stub._pending_resolution["category"].startswith("verify:")


def test_gate_recalls_solution_hint_when_known(tmp_path, monkeypatch):
    _, sm = _isolate_memories(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    _make_failing_py(proj)
    stub = _GateStub()

    # 第一次红：拿到这类错误的 category + 文本，预先登记一条解法
    msgs1 = []
    asyncio.run(stub._run_verify_gate(str(proj), 0, msgs1, "s1"))
    pend = stub._pending_resolution
    assert "解法记忆" not in msgs1[0]["content"]   # 首次无解法历史
    sm.record_resolution(pend["category"], pend["error_text"],
                         note="把断言期望值改对", repair_rounds=2)

    # 第二次同类红：解法记忆命中 → 附正向提示
    msgs2 = []
    asyncio.run(stub._run_verify_gate(str(proj), 0, msgs2, "s2"))
    assert "解法记忆" in msgs2[0]["content"]
    assert "可解" in msgs2[0]["content"]


def test_gate_registers_resolution_on_green(tmp_path, monkeypatch):
    _, sm = _isolate_memories(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    _make_failing_py(proj)
    stub = _GateStub()

    # 红一轮：记 pending
    asyncio.run(stub._run_verify_gate(str(proj), 0, [], "s1"))
    assert stub._pending_resolution is not None
    assert sm.all() == {}   # 还没解决，解法库为空

    # 修好后转绿：闸门确认绿 → 登记解法（repair_rounds>0）
    _make_passing_py(proj)
    action, _ = asyncio.run(stub._run_verify_gate(str(proj), 1, [], "s2"))
    assert action == "pass"
    assert len(sm.all()) == 1               # 已登记一条解法
    assert stub._pending_resolution is None  # pending 已清
    entry = next(iter(sm.all().values()))
    assert entry["resolved_count"] == 1
    assert entry["rounds_last"] == 1
