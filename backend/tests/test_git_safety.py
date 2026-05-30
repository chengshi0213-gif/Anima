#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_git_safety.py — 工程安全网（M9）单元测试 (pytest)

不触网、不调模型。验证：
  - git 仓库：checkpoint 非破坏性、rollback 把已跟踪文件恢复到快照、
    保留 agent 新建的未跟踪文件、还原快照时的 WIP。
  - 非 git 目录：文件拷贝快照 + 回滚。
  - executor 确实挂载了 checkpoint/rollback 工具。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_git_safety.py -v
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import git_safety as gs  # noqa: E402


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _init_git_repo(d: Path):
    _git(["init"], d)
    _git(["config", "user.email", "t@t.com"], d)
    _git(["config", "user.name", "t"], d)
    _git(["config", "commit.gpgsign", "false"], d)
    (d / "app.py").write_text("print('v1')\n", encoding="utf-8")
    _git(["add", "-A"], d)
    _git(["commit", "-m", "init"], d)


# ── git 模式 ───────────────────────────────────────────────────────────────

def test_checkpoint_and_rollback_git(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    _init_git_repo(repo)
    p = str(repo)

    cp = gs.checkpoint(p, label="改动前")
    assert "checkpoint_id" in cp and cp["mode"] == "git"
    cp_id = cp["checkpoint_id"]

    # agent 改崩了已跟踪文件 + 新建一个未跟踪文件
    (repo / "app.py").write_text("BROKEN garbage\n", encoding="utf-8")
    (repo / "new_junk.py").write_text("# agent created\n", encoding="utf-8")

    r = gs.rollback(p, cp_id)
    assert r["status"] == "rolled_back" and r["mode"] == "git"
    # 已跟踪文件恢复
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('v1')\n"
    # 未跟踪文件保留，不误删
    assert (repo / "new_junk.py").exists()


def test_checkpoint_captures_dirty_wip(tmp_path):
    """快照时有未提交的 WIP，回滚后 WIP 被还原。"""
    repo = tmp_path / "proj"
    repo.mkdir()
    _init_git_repo(repo)
    p = str(repo)

    # 快照前先有一处未提交改动（用户的 WIP）
    (repo / "app.py").write_text("print('wip')\n", encoding="utf-8")
    cp = gs.checkpoint(p)
    assert cp["dirty_captured"] is True
    cp_id = cp["checkpoint_id"]

    # agent 把它改坏
    (repo / "app.py").write_text("destroyed\n", encoding="utf-8")
    r = gs.rollback(p, cp_id)
    assert r["wip_restored"] is True
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('wip')\n"


def test_checkpoint_is_non_destructive(tmp_path):
    """打快照本身不改动工作区/不动 stash 列表。"""
    repo = tmp_path / "proj"
    repo.mkdir()
    _init_git_repo(repo)
    p = str(repo)
    (repo / "app.py").write_text("print('wip')\n", encoding="utf-8")

    gs.checkpoint(p)

    # 工作区内容原封不动
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('wip')\n"
    # stash 列表为空（我们用的是 stash create，不入栈）
    stash_list = _git(["stash", "list"], repo).stdout.strip()
    assert stash_list == ""


# ── 文件拷贝模式（非 git）──────────────────────────────────────────────────

def test_checkpoint_and_rollback_copy(tmp_path):
    proj = tmp_path / "plain"
    proj.mkdir()
    (proj / "main.py").write_text("ORIGINAL\n", encoding="utf-8")
    (proj / "node_modules").mkdir()
    (proj / "node_modules" / "huge.bin").write_text("x" * 1000, encoding="utf-8")
    p = str(proj)

    cp = gs.checkpoint(p)
    assert cp["mode"] == "copy"
    cp_id = cp["checkpoint_id"]
    # 重目录被跳过
    snap = proj / gs._SNAP_DIRNAME / cp_id
    assert not (snap / "node_modules").exists()

    (proj / "main.py").write_text("CORRUPTED\n", encoding="utf-8")
    r = gs.rollback(p, cp_id)
    assert r["status"] == "rolled_back" and r["mode"] == "copy"
    assert (proj / "main.py").read_text(encoding="utf-8") == "ORIGINAL\n"


def test_list_checkpoints(tmp_path):
    proj = tmp_path / "plain"
    proj.mkdir()
    (proj / "a.txt").write_text("hi", encoding="utf-8")
    p = str(proj)
    gs.checkpoint(p, label="one")
    gs.checkpoint(p, label="two")
    out = gs.list_checkpoints(p)
    assert out["count"] == 2
    labels = {c["label"] for c in out["checkpoints"]}
    assert labels == {"one", "two"}


def test_list_no_double_count_in_git_repo(tmp_path):
    """回归：git 顶层（正斜杠）与自身目录（反斜杠）在 Windows 上别名同一目录，
    去重失败会把同一份 index.json 数两遍。打 1 个快照只能列出 1 个。"""
    repo = tmp_path / "proj"
    repo.mkdir()
    _init_git_repo(repo)
    p = str(repo)
    gs.checkpoint(p, label="only-one")
    out = gs.list_checkpoints(p)
    assert out["count"] == 1


def test_rollback_unknown_id(tmp_path):
    proj = tmp_path / "plain"
    proj.mkdir()
    (proj / "a.txt").write_text("hi", encoding="utf-8")
    r = gs.rollback(str(proj), "cp_doesnotexist")
    assert "error" in r


def test_checkpoint_missing_path():
    r = gs.checkpoint("E:/no/such/dir/xyz123")
    assert "error" in r


# ── 注册 ──────────────────────────────────────────────────────────────────

def test_tool_defs_and_dispatch():
    names = {d["function"]["name"] for d in gs.GIT_SAFETY_TOOL_DEFS}
    assert names == {"checkpoint", "rollback", "list_checkpoints"}
    d = gs.build_git_safety_dispatch()
    assert set(d) == {"checkpoint", "rollback", "list_checkpoints"}
    assert all(callable(f) for f in d.values())


def test_executor_has_safety_tools():
    from executor_worker import ExecutorWorker
    w = ExecutorWorker()
    tool_names = {d["function"]["name"] for d in w.tool_defs}
    assert "checkpoint" in tool_names
    assert "rollback" in tool_names
    assert callable(w.tool_dispatch["checkpoint"])
    assert callable(w.tool_dispatch["rollback"])
