#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V (v1.3) Verify 闸门测试：纯函数 + AgentBase._run_verify_gate 集成。"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verify_gate import (
    detect_verify_command, looks_like_verify, summarize_failure,
    run_verification, format_repair_message,
)
from agent_base import AgentBase


# ── detect_verify_command ────────────────────────────────────────────────
def test_detect_python_tests_dir(tmp_path):
    (tmp_path / "tests").mkdir()
    cmd, kind = detect_verify_command(str(tmp_path))
    assert kind == "pytest"
    assert "pytest" in cmd


def test_detect_python_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    cmd, kind = detect_verify_command(str(tmp_path))
    assert kind == "pytest"


def test_detect_node_npm_test(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"test":"jest"}}', encoding="utf-8")
    cmd, kind = detect_verify_command(str(tmp_path))
    assert kind == "npm"
    assert "test" in cmd


def test_detect_node_tsc_no_test_script(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    cmd, kind = detect_verify_command(str(tmp_path))
    assert kind == "tsc"


def test_detect_rust(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")
    cmd, kind = detect_verify_command(str(tmp_path))
    assert kind == "cargo"


def test_detect_none_for_empty_dir(tmp_path):
    assert detect_verify_command(str(tmp_path)) is None


def test_detect_none_for_missing_path():
    assert detect_verify_command(None) is None
    assert detect_verify_command("/no/such/path/xyz") is None


# ── looks_like_verify ────────────────────────────────────────────────────
@pytest.mark.parametrize("cmd", [
    "pytest -q", "python -m pytest tests/", "npm test", "npm run test",
    "npx tsc --noEmit", "cargo test", "go test ./...", "ruff check .",
    "mypy backend/", "yarn test",
])
def test_looks_like_verify_true(cmd):
    assert looks_like_verify(cmd) is True


@pytest.mark.parametrize("cmd", [
    "ls -la", "echo hi", "git status", "python build.py", "cat file.txt", "",
])
def test_looks_like_verify_false(cmd):
    assert looks_like_verify(cmd) is False


# ── summarize_failure ────────────────────────────────────────────────────
def test_summarize_pytest_failed_lines():
    stdout = "FAILED tests/test_a.py::test_x - AssertionError\n=== 1 failed ==="
    out = summarize_failure(stdout, "")
    assert "FAILED tests/test_a.py::test_x" in out


def test_summarize_tsc_error():
    stdout = "src/a.ts(3,5): error TS2304: Cannot find name 'foo'."
    out = summarize_failure(stdout, "")
    assert "TS2304" in out


def test_summarize_generic_traceback_fallback():
    stderr = "Traceback (most recent call last):\n  File x\nValueError: boom"
    out = summarize_failure("", stderr)
    assert "ValueError" in out or "Traceback" in out


def test_summarize_tail_when_no_signal():
    out = summarize_failure("line1\nline2\nline3", "")
    assert "line3" in out


# ── run_verification（真跑 pytest，临时项目）─────────────────────────────
def _make_py_project(tmp_path, passing: bool):
    (tmp_path / "tests").mkdir()
    body = "def test_ok():\n    assert 1 == 1\n" if passing \
        else "def test_bad():\n    assert 1 == 2\n"
    (tmp_path / "tests" / "test_sample.py").write_text(body, encoding="utf-8")


def test_run_verification_green(tmp_path):
    _make_py_project(tmp_path, passing=True)
    res = run_verification(str(tmp_path), timeout=60)
    assert res["ran"] is True
    assert res["ok"] is True
    assert res["exit_code"] == 0


def test_run_verification_red(tmp_path):
    _make_py_project(tmp_path, passing=False)
    res = run_verification(str(tmp_path), timeout=60)
    assert res["ran"] is True
    assert res["ok"] is False
    assert res["exit_code"] != 0
    assert res["failure_summary"]   # 非空


def test_run_verification_no_command(tmp_path):
    res = run_verification(str(tmp_path))
    assert res["ran"] is False
    assert res["ok"] is False


# ── format_repair_message ────────────────────────────────────────────────
def test_format_repair_message_contains_context():
    result = {"command": "pytest -q", "exit_code": 1,
              "failure_summary": "FAILED test_x - AssertionError"}
    msg = format_repair_message(result, 1, 3)
    assert "pytest -q" in msg
    assert "1/3" in msg
    assert "AssertionError" in msg


# ── AgentBase._run_verify_gate 集成（用 stub，不触网）─────────────────────
class _GateStub:
    """最小对象：只提供 _run_verify_gate 依赖的属性，不走 AgentBase.__init__。"""
    max_repair_rounds = 3

    def _log(self, *a, **k):
        pass

    _run_verify_gate = AgentBase._run_verify_gate


def test_gate_pass_on_green(tmp_path):
    _make_py_project(tmp_path, passing=True)
    stub = _GateStub()
    messages = []
    action, rounds = asyncio.run(
        stub._run_verify_gate(str(tmp_path), 0, messages, "sid"))
    assert action == "pass"
    assert messages == []   # 绿不注入修复消息


def test_gate_repair_on_red(tmp_path):
    _make_py_project(tmp_path, passing=False)
    stub = _GateStub()
    messages = []
    action, rounds = asyncio.run(
        stub._run_verify_gate(str(tmp_path), 0, messages, "sid"))
    assert action == "repair"
    assert rounds == 1
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert "自动验证闸门" in messages[0]["content"]


def test_gate_unverified_when_exhausted(tmp_path):
    _make_py_project(tmp_path, passing=False)
    stub = _GateStub()
    messages = []
    # 已用满修复额度 → 不再注入，标记 unverified
    action, rounds = asyncio.run(
        stub._run_verify_gate(str(tmp_path), 3, messages, "sid"))
    assert action == "unverified"
    assert messages == []


def test_gate_pass_when_no_verify_command(tmp_path):
    # 探测不到验证命令 → 无法把关，放行（不阻塞交付）
    stub = _GateStub()
    messages = []
    action, rounds = asyncio.run(
        stub._run_verify_gate(str(tmp_path), 0, messages, "sid"))
    assert action == "pass"
