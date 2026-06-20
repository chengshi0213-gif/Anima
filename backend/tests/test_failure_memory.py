#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R (v1.3) 跨会话失败记忆测试：签名归一化 + 持久化知识库 + 闸门接入。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from failure_memory import (
    error_signature, FailureMemory, format_recall_hint, get_failure_memory,
)
from agent_base import AgentBase


# ── error_signature：同类错误同签名，不同类不同 ──────────────────────────
def test_signature_stable_across_paths_and_lines():
    # 同一个 AssertionError，路径和行号不同 → 应是同一签名
    a = "FAILED C:\\proj\\tests\\test_a.py::test_x - AssertionError: expected 1"
    b = "FAILED C:\\proj\\tests\\test_b.py::test_y - AssertionError: expected 1"
    assert error_signature("verify:pytest", a) == error_signature("verify:pytest", b)


def test_signature_stable_across_numbers():
    a = "ValueError at line 42: bad index 7"
    b = "ValueError at line 99: bad index 3"
    assert error_signature("v", a) == error_signature("v", b)


def test_signature_differs_by_error_type():
    a = "AssertionError: boom"
    b = "ImportError: no module named x"
    assert error_signature("v", a) != error_signature("v", b)


def test_signature_differs_by_category():
    txt = "AssertionError: boom"
    assert error_signature("verify:pytest", txt) != error_signature("verify:npm", txt)


def test_signature_carries_error_type_tag():
    sig = error_signature("verify:tsc", "src/a.ts: error TS2304: name")
    assert "ts2304" in sig


# ── FailureMemory：record / recall / 持久化 ──────────────────────────────
def test_record_then_recall(tmp_path):
    fm = FailureMemory(tmp_path / "fm.json")
    assert fm.recall("verify:pytest", "AssertionError: x") is None  # 首次无历史
    fm.record("verify:pytest", "AssertionError: x")
    entry = fm.recall("verify:pytest", "AssertionError: x")
    assert entry is not None
    assert entry["count"] == 1


def test_record_increments_count(tmp_path):
    fm = FailureMemory(tmp_path / "fm.json")
    fm.record("v", "AssertionError: x at line 1")
    fm.record("v", "AssertionError: x at line 2")   # 归一后同签名
    entry = fm.recall("v", "AssertionError: x at line 3")
    assert entry["count"] == 2


def test_persistence_across_instances(tmp_path):
    p = tmp_path / "fm.json"
    fm1 = FailureMemory(p)
    fm1.record("v", "ImportError at line 5: cannot import name")
    fm2 = FailureMemory(p)   # 新实例从磁盘加载
    # 同类错误（仅行号不同 → 数字归一后同签名）
    entry = fm2.recall("v", "ImportError at line 9: cannot import name")
    assert entry is not None
    assert entry["count"] == 1


def test_first_summary_preserved(tmp_path):
    fm = FailureMemory(tmp_path / "fm.json")
    # 同类错误（仅期望值数字不同 → 归一后同签名）
    fm.record("v", "AssertionError: expected 1", summary="原始摘要 original")
    fm.record("v", "AssertionError: expected 2", summary="后来的摘要 later")
    entry = fm.recall("v", "AssertionError: expected 3")
    assert "original" in entry["summary"]   # 首次摘要保留，不被覆盖


def test_all_returns_copy(tmp_path):
    fm = FailureMemory(tmp_path / "fm.json")
    fm.record("v", "X Error")
    snapshot = fm.all()
    snapshot.clear()
    assert len(fm.all()) == 1   # 改副本不影响内部


def test_corrupt_file_recovers(tmp_path):
    p = tmp_path / "fm.json"
    p.write_text("{not valid json", encoding="utf-8")
    fm = FailureMemory(p)   # 不崩，当空库
    assert fm.all() == {}
    fm.record("v", "Y Error")
    assert len(fm.all()) == 1


# ── format_recall_hint ───────────────────────────────────────────────────
def test_format_recall_hint_mentions_count():
    hint = format_recall_hint({"count": 3, "summary": "AssertionError: boom"})
    assert "3" in hint
    assert "失败记忆" in hint
    assert "boom" in hint


# ── 闸门接入：红时记录 + 第二次命中提示（用 stub 不触网）─────────────────
class _GateStub:
    max_repair_rounds = 3

    def _log(self, *a, **k):
        pass

    _run_verify_gate = AgentBase._run_verify_gate


def _make_failing_py(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_s.py").write_text(
        "def test_bad():\n    assert 1 == 2\n", encoding="utf-8")


def test_gate_records_and_recalls_on_repeat(tmp_path, monkeypatch):
    # 把失败记忆指向临时文件（隔离全局单例）
    import failure_memory as fmmod
    fm = fmmod.FailureMemory(tmp_path / "fm.json")
    monkeypatch.setattr(fmmod, "_SINGLETON", fm)

    proj = tmp_path / "proj"
    proj.mkdir()
    _make_failing_py(proj)

    stub = _GateStub()

    # 第一次失败：record 但 recall 在 record 前 → 无"似曾相识"提示
    msgs1 = []
    action1, _ = asyncio.run(stub._run_verify_gate(str(proj), 0, msgs1, "s1"))
    assert action1 == "repair"
    assert "失败记忆" not in msgs1[0]["content"]
    assert fm.all()   # 已记录

    # 第二次同类失败（新会话）：recall 命中 → 附"似曾相识"提示
    msgs2 = []
    action2, _ = asyncio.run(stub._run_verify_gate(str(proj), 0, msgs2, "s2"))
    assert action2 == "repair"
    assert "失败记忆" in msgs2[0]["content"]
