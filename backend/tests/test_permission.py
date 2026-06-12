#!/usr/bin/env python3
"""test_permission.py — D3: 权限分级单元测试"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import permission as perm  # noqa: E402


def test_auto_mode_allows_all(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "auto")
    monkeypatch.setattr(perm, "_get_rules", lambda: [])
    assert perm.check_tool_permission("file_write", {"path": "a.py"}) is None
    assert perm.check_tool_permission("shell_run", {"command": "rm -rf /"}) is None


def test_readonly_blocks_writes(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "readonly")
    monkeypatch.setattr(perm, "_get_rules", lambda: [])
    r = perm.check_tool_permission("file_write", {"path": "a.py"})
    assert r is not None and r.startswith("deny:")
    r2 = perm.check_tool_permission("shell_run", {"command": "ls"})
    assert r2 is not None and r2.startswith("deny:")


def test_readonly_allows_reads(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "readonly")
    monkeypatch.setattr(perm, "_get_rules", lambda: [])
    assert perm.check_tool_permission("file_read", {"path": "a.py"}) is None
    assert perm.check_tool_permission("search_code", {"pattern": "foo"}) is None


def test_confirm_mode_flags_writes(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "confirm")
    monkeypatch.setattr(perm, "_get_rules", lambda: [])
    assert perm.check_tool_permission("file_write", {"path": "a.py"}) == "confirm"
    assert perm.check_tool_permission("shell_run", {"command": "ls"}) == "confirm"
    assert perm.check_tool_permission("file_read", {}) is None


def test_accept_edits_allows_edits(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "acceptEdits")
    monkeypatch.setattr(perm, "_get_rules", lambda: [])
    assert perm.check_tool_permission("file_write", {"path": "a.py"}) is None
    assert perm.check_tool_permission("file_edit", {"path": "a.py"}) is None
    assert perm.check_tool_permission("apply_patch", {"patch": "..."}) is None


def test_accept_edits_confirms_shell(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "acceptEdits")
    monkeypatch.setattr(perm, "_get_rules", lambda: [])
    assert perm.check_tool_permission("shell_run", {"command": "rm"}) == "confirm"
    assert perm.check_tool_permission("git_commit", {"path": "."}) == "confirm"


def test_rule_deny_pattern(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "auto")
    monkeypatch.setattr(perm, "_get_rules", lambda: [
        {"tool": "shell_run", "pattern": r"rm\s", "action": "deny"},
    ])
    r = perm.check_tool_permission("shell_run", {"command": "rm -rf /"})
    assert r is not None and "deny" in r
    assert perm.check_tool_permission("shell_run", {"command": "ls"}) is None


def test_rule_deny_path(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "auto")
    monkeypatch.setattr(perm, "_get_rules", lambda: [
        {"tool": "file_write", "path": "**/.env*", "action": "deny"},
    ])
    r = perm.check_tool_permission("file_write", {"path": "src/.env.local"})
    assert r is not None and "deny" in r
    assert perm.check_tool_permission("file_write", {"path": "src/app.py"}) is None


def test_rule_confirm(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "auto")
    monkeypatch.setattr(perm, "_get_rules", lambda: [
        {"tool": "shell_run", "pattern": "npm publish", "action": "confirm"},
    ])
    assert perm.check_tool_permission("shell_run", {"command": "npm publish"}) == "confirm"
    assert perm.check_tool_permission("shell_run", {"command": "npm install"}) is None


def test_rule_overrides_mode(monkeypatch):
    monkeypatch.setattr(perm, "_get_mode", lambda: "auto")
    monkeypatch.setattr(perm, "_get_rules", lambda: [
        {"tool": "file_write", "path": "**/secrets.json", "action": "deny"},
    ])
    r = perm.check_tool_permission("file_write", {"path": "config/secrets.json"})
    assert r is not None and "deny" in r
