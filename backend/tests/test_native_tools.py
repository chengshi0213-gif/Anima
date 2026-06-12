#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_native_tools.py — v1.2.1 原生工具层单元测试 (pytest)

T1: glob_files（按文件名模式找文件）+ map_project（项目全景树）。
后续 T2-T7（long_run/install_pkg/read_image/read_pdf/http_request/git）陆续追加到本文件。

运行:
    cd E:\\AI\\workspace\\Anima\\backend
    python -m pytest tests/test_native_tools.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import xi_worker as xw  # noqa: E402
import capabilities  # noqa: E402


@pytest.fixture
def sample_tree(tmp_path):
    """造一个含噪声目录的小项目树。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "src" / "util.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test(): pass", encoding="utf-8")
    (tmp_path / "README.md").write_text("# proj", encoding="utf-8")
    # 噪声：应被 map_project 跳过
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("nope", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    return tmp_path


# ── T1: glob_files ────────────────────────────────────────────────────────────

def test_glob_files_recursive(sample_tree):
    r = xw._glob_files("**/*.py", str(sample_tree))
    assert "error" not in r
    names = {Path(f).name for f in r["files"]}
    assert names == {"app.py", "util.py", "test_app.py"}
    assert r["count"] == 3


def test_glob_files_pattern_filters(sample_tree):
    r = xw._glob_files("**/test_*.py", str(sample_tree))
    assert {Path(f).name for f in r["files"]} == {"test_app.py"}


def test_glob_files_sorted_by_mtime_desc(sample_tree):
    # 显式设置 mtime：util.py 最新，app.py 最旧
    os.utime(sample_tree / "src" / "app.py", (1000, 1000))
    os.utime(sample_tree / "tests" / "test_app.py", (2000, 2000))
    os.utime(sample_tree / "src" / "util.py", (3000, 3000))
    r = xw._glob_files("**/*.py", str(sample_tree))
    order = [Path(f).name for f in r["files"]]
    assert order == ["util.py", "test_app.py", "app.py"]


def test_glob_files_limit_and_truncated(sample_tree):
    r = xw._glob_files("**/*.py", str(sample_tree), limit=2)
    assert r["count"] == 2
    assert r["truncated"] is True


def test_glob_files_missing_path():
    r = xw._glob_files("*.py", "/no/such/dir/xyz")
    assert "error" in r


# ── T1: map_project ───────────────────────────────────────────────────────────

def test_map_project_skips_noise(sample_tree):
    r = xw._map_project(str(sample_tree))
    assert "error" not in r
    tree = r["tree"]
    assert "app.py" in tree and "README.md" in tree
    # 噪声目录及其内容不出现
    assert "node_modules" not in tree
    assert "junk.js" not in tree
    assert ".git" not in tree


def test_map_project_counts(sample_tree):
    r = xw._map_project(str(sample_tree))
    # 目录 src + tests（node_modules/.git 被跳过）
    assert r["dirs"] == 2
    # 文件 app.py/util.py/test_app.py/README.md
    assert r["files"] == 4


def test_map_project_respects_depth(sample_tree):
    # max_depth=0 → 只列根层条目，不进入子目录内容
    r = xw._map_project(str(sample_tree), max_depth=0)
    tree = r["tree"]
    assert "src/" in tree
    assert "app.py" not in tree   # 深度 1 的内容不展开


def test_map_project_missing_root():
    r = xw._map_project("/no/such/root/xyz")
    assert "error" in r


# ── 注册到 execution capability ───────────────────────────────────────────────

def test_execution_cap_registers_t1_tools():
    cap = capabilities.build(["execution"], agent_id="xi")
    names = {d["function"]["name"] for d in cap["tool_defs"]}
    assert "glob_files" in names
    assert "map_project" in names
    assert "glob_files" in cap["dispatch"]
    assert "map_project" in cap["dispatch"]


def test_execution_cap_dispatch_runs(sample_tree):
    cap = capabilities.build(["execution"], agent_id="xi")
    out = cap["dispatch"]["glob_files"](pattern="**/*.md", path=str(sample_tree))
    assert {Path(f).name for f in out["files"]} == {"README.md"}
    out2 = cap["dispatch"]["map_project"](root=str(sample_tree))
    assert "node_modules" not in out2["tree"]
