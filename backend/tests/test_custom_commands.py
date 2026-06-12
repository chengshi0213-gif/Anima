#!/usr/bin/env python3
"""test_custom_commands.py — D7: .anima/commands/*.md 自定义命令"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import custom_commands as cc  # noqa: E402

_FIX_MD = """\
---
description: 自动修复常见代码问题
---
请修复以下文件中的所有 lint 错误：$ARGUMENTS
"""


def _make_cmd_dir(tmp_path, name="fix", content=_FIX_MD):
    proj = tmp_path / "proj"
    cmds_dir = proj / ".anima" / "commands"
    cmds_dir.mkdir(parents=True)
    (cmds_dir / f"{name}.md").write_text(content, encoding="utf-8")
    return str(proj)


def test_list_commands(tmp_path):
    proj = _make_cmd_dir(tmp_path)
    cmds = cc.list_commands(proj)
    assert len(cmds) == 1
    assert cmds[0]["name"] == "fix"
    assert "修复" in cmds[0]["description"]


def test_list_commands_empty(tmp_path):
    assert cc.list_commands(str(tmp_path)) == []


def test_load_command_replaces_arguments(tmp_path):
    proj = _make_cmd_dir(tmp_path)
    body = cc.load_command("fix", proj, "src/app.py")
    assert body is not None
    assert "src/app.py" in body
    assert "$ARGUMENTS" not in body


def test_load_command_not_found(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    assert cc.load_command("nonexist", str(proj)) is None


def test_load_command_no_frontmatter(tmp_path):
    content = "直接跑测试并修复失败用例"
    proj = _make_cmd_dir(tmp_path, name="test-fix", content=content)
    body = cc.load_command("test-fix", proj)
    assert "测试" in body


def test_parse_command_md_missing(tmp_path):
    assert cc._parse_command_md(tmp_path / "no.md") is None


# ── executor_worker integration ──

from executor_worker import _build_command_index, _run_command  # noqa: E402


def test_build_command_index(tmp_path):
    proj = _make_cmd_dir(tmp_path)
    idx = _build_command_index(proj)
    assert "/fix" in idx
    assert "修复" in idx


def test_build_command_index_no_project():
    assert _build_command_index(None) == ""


def test_run_command_success(tmp_path):
    proj = _make_cmd_dir(tmp_path)
    r = _run_command("fix", "main.py", proj)
    assert r.get("command") == "fix"
    assert "main.py" in r["prompt"]


def test_run_command_not_found(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    r = _run_command("nope", "", str(proj))
    assert "error" in r
