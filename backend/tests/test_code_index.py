#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase L code_index 测试。

覆盖：
  - Python AST 索引（symbol/import 精确提取）
  - 增量 SHA256 缓存（没改的文件不重扫）
  - locate_relevant 评分（符号>路径>导入，测试文件降权）
  - find_symbol_ast 精确定位（含多文件）
  - 非 Python 文件 regex 回退
  - 无文件上限（覆盖 code_intel._walk_files limit=5000 的替换）
"""
import sys
import shutil
import textwrap
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code_index import (
    build_index, get_index, locate_relevant, find_symbol_ast,
    _file_sha256, _tokenize, _index_python, _index_fallback,
)


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_proj(tmp_path):
    """一个小型多文件 Python 项目。"""
    (tmp_path / "alpha.py").write_text(textwrap.dedent("""\
        def do_work(x):
            return x * 2

        class Engine:
            pass

        MAX_RETRIES = 3
    """), encoding="utf-8")

    (tmp_path / "beta.py").write_text(textwrap.dedent("""\
        from alpha import do_work, Engine

        def run_engine():
            e = Engine()
            return do_work(1)
    """), encoding="utf-8")

    (tmp_path / "test_alpha.py").write_text(textwrap.dedent("""\
        from alpha import do_work
        def test_do_work():
            assert do_work(3) == 6
    """), encoding="utf-8")

    (tmp_path / "helper.ts").write_text(textwrap.dedent("""\
        export function slugify(s: string): string {
            return s.toLowerCase().replace(/ /g, '-');
        }
        export class Formatter { }
    """), encoding="utf-8")

    return tmp_path


# ── _tokenize ────────────────────────────────────────────────────────────────

def test_tokenize_snake():
    assert "verify" in _tokenize("verify_gate")
    assert "gate" in _tokenize("verify_gate")


def test_tokenize_camel():
    assert "executor" in _tokenize("ExecutorWorker")
    assert "worker" in _tokenize("ExecutorWorker")


def test_tokenize_path():
    tokens = _tokenize("backend/agent_tools.py")
    assert "backend" in tokens
    assert "agent" in tokens
    assert "tools" in tokens


# ── Python AST 索引 ──────────────────────────────────────────────────────────

def test_ast_extracts_functions(tmp_path):
    (tmp_path / "f.py").write_text("def foo(): pass\nasync def bar(): pass\n")
    entry = _index_python(tmp_path / "f.py", tmp_path)
    names = {s.name for s in entry.symbols}
    assert "foo" in names
    assert "bar" in names


def test_ast_extracts_classes(tmp_path):
    (tmp_path / "c.py").write_text("class Alpha:\n    pass\nclass Beta(Alpha):\n    pass\n")
    entry = _index_python(tmp_path / "c.py", tmp_path)
    names = {s.name for s in entry.symbols}
    assert {"Alpha", "Beta"} <= names


def test_ast_extracts_imports(tmp_path):
    src = "import os\nimport sys\nfrom pathlib import Path\nfrom agent_base import AgentBase\n"
    (tmp_path / "i.py").write_text(src)
    entry = _index_python(tmp_path / "i.py", tmp_path)
    assert "os" in entry.imports
    assert "sys" in entry.imports
    assert "pathlib" in entry.imports
    assert "agent_base" in entry.imports


def test_ast_syntax_error_falls_back(tmp_path):
    (tmp_path / "bad.py").write_text("def oops(:\n    pass\n")
    entry = _index_python(tmp_path / "bad.py", tmp_path)
    assert isinstance(entry.symbols, list)   # 回退不抛异常


# ── 非 Python 回退 ────────────────────────────────────────────────────────────

def test_ts_fallback_functions(tmp_proj):
    entry = _index_fallback(tmp_proj / "helper.ts", tmp_proj)
    names = {s.name for s in entry.symbols}
    assert "slugify" in names


def test_ts_fallback_classes(tmp_proj):
    entry = _index_fallback(tmp_proj / "helper.ts", tmp_proj)
    kinds = {s.name: s.kind for s in entry.symbols}
    assert kinds.get("Formatter") == "class"


# ── build_index ───────────────────────────────────────────────────────────────

def test_build_index_covers_all_files(tmp_proj):
    idx = build_index(tmp_proj, force=True)
    rels = set(idx.keys())
    assert "alpha.py" in rels
    assert "beta.py" in rels
    assert "test_alpha.py" in rels
    assert "helper.ts" in rels


def test_build_index_no_file_limit(tmp_path):
    """没有 5000 文件上限（与 code_intel._walk_files 的差异）。"""
    for i in range(50):
        (tmp_path / f"m{i:03d}.py").write_text(f"def func_{i}(): pass\n")
    idx = build_index(tmp_path, force=True)
    assert len(idx) == 50


def test_sha256_caching(tmp_proj):
    """文件未改时，二次 build_index 不重新索引（缓存命中）。"""
    idx1 = build_index(tmp_proj, force=True)
    sha_before = {rel: e.sha256 for rel, e in idx1.items()}
    idx2 = build_index(tmp_proj, force=False)    # 增量
    for rel, e in idx2.items():
        assert e.sha256 == sha_before[rel], f"{rel} SHA256 changed unexpectedly"


def test_incremental_picks_up_changes(tmp_proj):
    """改一个文件后，增量构建只更新该文件的符号。"""
    build_index(tmp_proj, force=True)
    # 修改 alpha.py，加新函数
    (tmp_proj / "alpha.py").write_text("def do_work(x): return x\ndef new_fn(): pass\n")
    idx2 = build_index(tmp_proj, force=False)
    sym_names = {s.name for s in idx2["alpha.py"].symbols}
    assert "new_fn" in sym_names


# ── get_index ─────────────────────────────────────────────────────────────────

def test_get_index_falls_back_to_build(tmp_proj):
    idx = get_index(tmp_proj)
    assert "alpha.py" in idx


# ── locate_relevant ───────────────────────────────────────────────────────────

def test_locate_by_exact_symbol(tmp_proj):
    build_index(tmp_proj, force=True)
    results = locate_relevant("Engine", tmp_proj)
    rels = [r["rel"] for r in results]
    assert "alpha.py" in rels
    assert rels.index("alpha.py") == 0    # 定义文件排第一


def test_locate_by_partial_token(tmp_proj):
    build_index(tmp_proj, force=True)
    results = locate_relevant("engine", tmp_proj)
    rels = [r["rel"] for r in results]
    assert "alpha.py" in rels


def test_locate_test_file_downranked(tmp_proj):
    """test_ 文件命中时，排名应低于同分量的非测试文件。"""
    build_index(tmp_proj, force=True)
    results = locate_relevant("do_work", tmp_proj)
    rels = [r["rel"] for r in results]
    assert "alpha.py" in rels
    assert "test_alpha.py" in rels
    assert rels.index("alpha.py") < rels.index("test_alpha.py")


def test_locate_by_import(tmp_proj):
    """beta.py 导入了 alpha → 查询 alpha 时 beta 也应出现。"""
    build_index(tmp_proj, force=True)
    results = locate_relevant("alpha", tmp_proj)
    rels = [r["rel"] for r in results]
    assert "alpha.py" in rels
    assert "beta.py" in rels


def test_locate_returns_top_k(tmp_proj):
    build_index(tmp_proj, force=True)
    results = locate_relevant("do_work engine", tmp_proj, top_k=2)
    assert len(results) <= 2


def test_locate_empty_query(tmp_proj):
    build_index(tmp_proj, force=True)
    assert locate_relevant("", tmp_proj) == []


# ── find_symbol_ast ──────────────────────────────────────────────────────────

def test_find_symbol_ast_finds_function(tmp_proj):
    build_index(tmp_proj, force=True)
    r = find_symbol_ast("do_work", tmp_proj)
    assert r["total"] == 1
    assert r["matches"][0]["file"] == "alpha.py"
    assert r["matches"][0]["type"] == "function"


def test_find_symbol_ast_finds_class(tmp_proj):
    build_index(tmp_proj, force=True)
    r = find_symbol_ast("Engine", tmp_proj)
    assert r["total"] >= 1
    files = {m["file"] for m in r["matches"]}
    assert "alpha.py" in files


def test_find_symbol_ast_case_insensitive(tmp_proj):
    build_index(tmp_proj, force=True)
    r = find_symbol_ast("engine", tmp_proj)    # 小写
    assert r["total"] >= 1


def test_find_symbol_ast_type_filter(tmp_proj):
    build_index(tmp_proj, force=True)
    r = find_symbol_ast("Engine", tmp_proj, symbol_type="function")
    # Engine 是 class，用 function 过滤应找不到
    for m in r["matches"]:
        assert m["type"] == "function"
    assert all(m["file"] != "alpha.py" for m in r["matches"])


def test_find_symbol_ast_missing(tmp_proj):
    build_index(tmp_proj, force=True)
    r = find_symbol_ast("NonExistentSymbol", tmp_proj)
    assert r["total"] == 0


def test_find_symbol_ast_empty_name(tmp_proj):
    r = find_symbol_ast("", tmp_proj)
    assert "error" in r
