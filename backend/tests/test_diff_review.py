#!/usr/bin/env python3
"""test_diff_review.py — D4 Diff 审查: _make_diff / _write_file / _edit_file 返回 diff"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from xi_worker import _make_diff, _write_file, _edit_file, _DIFF_MAX_LINES  # noqa: E402


def test_make_diff_basic():
    d = _make_diff("a\nb\n", "a\nc\n", "/tmp/x.py")
    assert "+c" in d
    assert "-b" in d


def test_make_diff_truncation():
    old = "\n".join(f"line{i}" for i in range(300))
    new = "\n".join(f"LINE{i}" for i in range(300))
    d = _make_diff(old, new, "big.py")
    assert "截断" in d
    lines = d.splitlines()
    assert len(lines) <= _DIFF_MAX_LINES + 2


def test_make_diff_identical():
    d = _make_diff("same\n", "same\n", "f.py")
    assert d == ""


def test_write_file_new_includes_diff(tmp_path):
    p = tmp_path / "new.txt"
    result = _write_file(str(p), "hello\n")
    assert "error" not in result
    assert "+hello" in result["diff"]


def test_write_file_overwrite_includes_diff(tmp_path):
    p = tmp_path / "exist.txt"
    p.write_text("old\n", encoding="utf-8")
    result = _write_file(str(p), "new\n")
    assert "-old" in result["diff"]
    assert "+new" in result["diff"]


def test_edit_file_includes_diff(tmp_path):
    p = tmp_path / "code.py"
    p.write_text("x = 1\ny = 2\n", encoding="utf-8")
    result = _edit_file(str(p), "x = 1", "x = 99")
    assert "error" not in result
    assert "-x = 1" in result["diff"]
    assert "+x = 99" in result["diff"]


def test_edit_file_error_no_diff(tmp_path):
    p = tmp_path / "code.py"
    p.write_text("x = 1\n", encoding="utf-8")
    result = _edit_file(str(p), "NOT_FOUND", "x = 99")
    assert "error" in result
    assert "diff" not in result
