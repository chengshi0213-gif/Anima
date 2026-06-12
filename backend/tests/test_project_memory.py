#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_project_memory.py — v1.2.2 A1 项目记忆系统单元测试 (pytest)

覆盖：多层级加载（全局/项目/个人/自动记忆/全局规则）、Claude Code 兼容检测顺序、
路径作用域规则匹配、Auto Memory 读写与裁剪。

运行:
    cd E:\\AI\\workspace\\Anima\\backend
    python -m pytest tests/test_project_memory.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import project_memory as pm  # noqa: E402


@pytest.fixture
def isolated_data_dir(monkeypatch, tmp_path):
    """把 project_memory.DATA_DIR 指到临时目录，不污染真实 ~/.anima/data。"""
    data_dir = tmp_path / "_data"
    data_dir.mkdir()
    monkeypatch.setattr(pm, "DATA_DIR", data_dir)
    return data_dir


def test_load_project_memory_empty_when_no_files(isolated_data_dir, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    assert pm.load_project_memory(str(proj)) == ""


def test_load_project_memory_no_work_dir(isolated_data_dir):
    assert pm.load_project_memory(None) == ""
    assert pm.load_project_memory("") == ""


def test_project_anima_md_loaded(isolated_data_dir, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "ANIMA.md").write_text("# 项目规范\n用 pytest 跑测试", encoding="utf-8")

    ctx = pm.load_project_memory(str(proj))
    assert "项目记忆（ANIMA.md）" in ctx
    assert "用 pytest 跑测试" in ctx


def test_compat_detection_order(isolated_data_dir, tmp_path):
    """检测顺序：ANIMA.md > CLAUDE.md > AGENTS.md > .cursorrules"""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "CLAUDE.md").write_text("CLAUDE 内容", encoding="utf-8")
    (proj / "AGENTS.md").write_text("AGENTS 内容", encoding="utf-8")

    ctx = pm.load_project_memory(str(proj))
    assert "CLAUDE.md" in ctx
    assert "CLAUDE 内容" in ctx
    assert "AGENTS 内容" not in ctx

    # 加上 ANIMA.md 后优先级更高
    (proj / "ANIMA.md").write_text("ANIMA 内容", encoding="utf-8")
    ctx2 = pm.load_project_memory(str(proj))
    assert "ANIMA.md" in ctx2
    assert "ANIMA 内容" in ctx2
    assert "CLAUDE 内容" not in ctx2


def test_global_and_local_memory(isolated_data_dir, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (pm.DATA_DIR / "ANIMA.md").write_text("全局偏好：用中文回复", encoding="utf-8")
    (proj / "ANIMA.local.md").write_text("本机测试库在 D:/data", encoding="utf-8")

    ctx = pm.load_project_memory(str(proj))
    assert "全局记忆" in ctx and "用中文回复" in ctx
    assert "个人记忆" in ctx and "本机测试库在 D:/data" in ctx


def test_long_file_truncated(isolated_data_dir, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "ANIMA.md").write_text("x" * (pm._MAX_FILE_CHARS + 500), encoding="utf-8")

    ctx = pm.load_project_memory(str(proj))
    assert "截断" in ctx


def test_auto_memory_roundtrip(isolated_data_dir, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()

    r = pm.append_auto_memory(str(proj), "测试命令：pytest -x --tb=short")
    assert r["ok"] is True

    raw = pm.read_auto_memory(str(proj))
    assert "测试命令：pytest -x --tb=short" in raw

    ctx = pm.load_project_memory(str(proj))
    assert "自动记忆" in ctx
    assert "测试命令：pytest -x --tb=short" in ctx


def test_auto_memory_empty_entry_rejected(isolated_data_dir, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    r = pm.append_auto_memory(str(proj), "   ")
    assert r["ok"] is False


def test_auto_memory_pruned_when_too_long(isolated_data_dir, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    # 每条目约占 4 行，需 >100 条才会越过 _MAX_MEMORY_LINES=400 触发裁剪
    for i in range(150):
        pm.append_auto_memory(str(proj), f"条目{i}\n第二行")

    raw = pm.read_auto_memory(str(proj))
    lines = raw.splitlines()
    assert len(lines) <= pm._MAX_MEMORY_LINES
    # 最早的条目应已被裁掉，最新的还在
    assert "条目149" in raw
    assert "条目0\n" not in raw


def test_repo_hash_stable_and_distinct(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert pm.repo_hash(str(a)) == pm.repo_hash(str(a))
    assert pm.repo_hash(str(a)) != pm.repo_hash(str(b))


def test_global_rules_no_paths_injected(isolated_data_dir, tmp_path):
    proj = tmp_path / "proj"
    rules = proj / ".anima" / "rules"
    rules.mkdir(parents=True)
    (rules / "style.md").write_text("# 风格\n所有代码用 4 空格缩进", encoding="utf-8")

    ctx = pm.load_project_memory(str(proj))
    assert "全局规则" in ctx
    assert "4 空格缩进" in ctx


def test_scoped_rules_path_match(isolated_data_dir, tmp_path):
    proj = tmp_path / "proj"
    rules = proj / ".anima" / "rules"
    rules.mkdir(parents=True)
    (rules / "testing.md").write_text(
        "---\npaths: [\"**/*.test.*\"]\n---\n测试文件必须 mock 网络请求",
        encoding="utf-8",
    )
    (rules / "api.md").write_text(
        "---\npaths: [\"src/api/**\"]\n---\nAPI 层禁止直接访问数据库",
        encoding="utf-8",
    )

    test_file = proj / "src" / "app.test.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("", encoding="utf-8")

    ctx = pm.get_scoped_rules(str(proj), str(test_file))
    assert "mock 网络请求" in ctx
    assert "禁止直接访问数据库" not in ctx

    # 不匹配任何规则的文件 → 空字符串
    other = proj / "src" / "util.py"
    other.write_text("", encoding="utf-8")
    assert pm.get_scoped_rules(str(proj), str(other)) == ""

    # 这条规则在「全局规则」里不应出现（因为带 paths，不是全局规则）
    base_ctx = pm.load_project_memory(str(proj))
    assert "全局规则" not in base_ctx
