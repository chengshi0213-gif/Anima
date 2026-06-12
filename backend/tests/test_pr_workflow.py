#!/usr/bin/env python3
"""test_pr_workflow.py — D6: git_push + create_pr + always-confirm 权限"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import git_tools as gt  # noqa: E402
import permission as perm  # noqa: E402


@pytest.fixture()
def git_repo(tmp_path):
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"],
                   cwd=str(tmp_path), capture_output=True)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"],
                   cwd=str(tmp_path), capture_output=True)
    return str(tmp_path)


# ── git_push ──

def test_git_push_not_a_repo(tmp_path):
    r = gt._git_push(str(tmp_path))
    assert "error" in r


def test_git_push_bad_remote():
    r = gt._git_push(".", remote="rm -rf /")
    assert "error" in r and "remote" in r["error"]


def test_git_push_bad_branch():
    r = gt._git_push(".", remote="origin", branch="a branch with spaces")
    assert "error" in r and "分支" in r["error"]


def test_git_push_no_remote(git_repo):
    r = gt._git_push(git_repo, remote="origin")
    assert r.get("pushed") is False or "error" in r


def test_git_push_infers_branch(git_repo):
    with patch.object(gt, "_run_git") as mock:
        mock.side_effect = [
            type("R", (), {"returncode": 0, "stdout": "true\n", "stderr": ""})(),
            type("R", (), {"returncode": 0, "stdout": "main\n", "stderr": ""})(),
            type("R", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})(),
        ]
        r = gt._git_push(git_repo)
        push_call = mock.call_args_list[2]
        assert "push" in push_call[0][0]
        assert "main" in push_call[0][0]


# ── create_pr ──

def test_create_pr_empty_title():
    r = gt._create_pr(".", title="")
    assert "error" in r and "标题" in r["error"]


def test_create_pr_no_gh(git_repo, monkeypatch):
    monkeypatch.setattr(gt.shutil, "which", lambda _: None)
    r = gt._create_pr(git_repo, title="Fix bug")
    assert "error" in r and "gh" in r["error"].lower()


def test_create_pr_success(git_repo, monkeypatch):
    monkeypatch.setattr(gt.shutil, "which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr(gt, "_ensure_repo", lambda p: None)
    fake_result = type("R", (), {
        "returncode": 0,
        "stdout": "https://github.com/user/repo/pull/42\n",
        "stderr": "",
    })()
    with patch("subprocess.run", return_value=fake_result) as mock:
        r = gt._create_pr(git_repo, title="Fix bug", body="Fixes #1", base="develop")
    assert r["created"] is True
    assert "42" in r["url"]
    args = mock.call_args[0][0]
    assert "--base" in args and "develop" in args


# ── always-confirm permission ──

def test_git_push_always_confirm(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "auto")
    monkeypatch.setattr(perm, "_get_rules", lambda: [])
    assert perm.check_tool_permission("git_push", {}) == "confirm"


def test_create_pr_always_confirm(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "auto")
    monkeypatch.setattr(perm, "_get_rules", lambda: [])
    assert perm.check_tool_permission("create_pr", {}) == "confirm"


def test_always_confirm_overrides_auto(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "auto")
    monkeypatch.setattr(perm, "_get_rules", lambda: [])
    assert perm.check_tool_permission("git_push", {"remote": "origin"}) == "confirm"
    assert perm.check_tool_permission("create_pr", {"title": "test"}) == "confirm"


# ── tool defs / dispatch shape ──

def test_tool_defs_include_push_and_pr():
    names = {d["function"]["name"] for d in gt.GIT_TOOL_DEFS}
    assert "git_push" in names
    assert "create_pr" in names


def test_dispatch_includes_push_and_pr():
    d = gt.build_git_dispatch()
    assert "git_push" in d and callable(d["git_push"])
    assert "create_pr" in d and callable(d["create_pr"])
