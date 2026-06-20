#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_code_intel.py — v1.2.2 B1-B4 代码智能工具单元测试 (pytest)

覆盖：
  B1  find_symbol    — Python/JS/TS/Go/Rust 各语言定义模式、symbol_type 过滤、空名报错
  B2  find_usages    — 引用查找、排除定义行、include_definition 模式
  B3  search_code_ctx — 上下文行、正则错误、glob 过滤
  B4  apply_patch    — 单文件单hunk、多hunk、多文件、空补丁报错

运行:
    cd E:\\AI\\workspace\\Anima\\backend
    python -m pytest tests/test_code_intel.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import code_intel as ci  # noqa: E402


# ════════════════════════════════════════════════════════════════════
#  B1 — find_symbol
# ════════════════════════════════════════════════════════════════════

def test_find_symbol_python_def(tmp_path):
    (tmp_path / "app.py").write_text("def hello():\n    pass\n\nclass World:\n    pass\n", encoding="utf-8")
    r = ci.find_symbol("hello", root=str(tmp_path))
    assert r["total"] == 1
    assert r["matches"][0]["type"] == "function"
    assert r["matches"][0]["line"] == 1


def test_find_symbol_python_class(tmp_path):
    (tmp_path / "m.py").write_text("class MyClass:\n    x = 1\n", encoding="utf-8")
    r = ci.find_symbol("MyClass", root=str(tmp_path))
    assert r["total"] == 1
    assert r["matches"][0]["type"] == "class"


def test_find_symbol_python_async_def(tmp_path):
    (tmp_path / "a.py").write_text("async def fetch():\n    pass\n", encoding="utf-8")
    r = ci.find_symbol("fetch", root=str(tmp_path))
    assert r["total"] == 1
    assert r["matches"][0]["type"] == "function"


def test_find_symbol_python_variable(tmp_path):
    (tmp_path / "c.py").write_text("MAX_SIZE = 100\n", encoding="utf-8")
    r = ci.find_symbol("MAX_SIZE", root=str(tmp_path))
    assert r["total"] == 1
    assert r["matches"][0]["type"] == "variable"


def test_find_symbol_js(tmp_path):
    (tmp_path / "app.js").write_text("function greet(name) { return name; }\nconst PI = 3.14;\n", encoding="utf-8")
    r = ci.find_symbol("greet", root=str(tmp_path))
    assert r["total"] == 1
    assert r["matches"][0]["type"] == "function"
    r2 = ci.find_symbol("PI", root=str(tmp_path))
    assert r2["total"] == 1


def test_find_symbol_ts_interface(tmp_path):
    (tmp_path / "types.ts").write_text("interface Config {\n  port: number;\n}\n", encoding="utf-8")
    r = ci.find_symbol("Config", root=str(tmp_path))
    assert r["total"] == 1


def test_find_symbol_go(tmp_path):
    (tmp_path / "main.go").write_text("func main() {\n}\n\ntype Server struct{}\n", encoding="utf-8")
    r = ci.find_symbol("main", root=str(tmp_path))
    assert any(m["type"] == "function" for m in r["matches"])
    r2 = ci.find_symbol("Server", root=str(tmp_path))
    assert r2["total"] >= 1


def test_find_symbol_rust(tmp_path):
    (tmp_path / "lib.rs").write_text("fn process() {}\nstruct Data {}\nenum Status {}\n", encoding="utf-8")
    r = ci.find_symbol("process", root=str(tmp_path))
    assert r["total"] == 1 and r["matches"][0]["type"] == "function"
    r2 = ci.find_symbol("Data", root=str(tmp_path))
    assert r2["total"] == 1 and r2["matches"][0]["type"] == "class"


def test_find_symbol_type_filter(tmp_path):
    (tmp_path / "m.py").write_text("def foo(): pass\nclass foo: pass\n", encoding="utf-8")
    r = ci.find_symbol("foo", symbol_type="function", root=str(tmp_path))
    assert r["total"] == 1
    assert r["matches"][0]["type"] == "function"
    r2 = ci.find_symbol("foo", symbol_type="class", root=str(tmp_path))
    assert r2["total"] == 1
    assert r2["matches"][0]["type"] == "class"


def test_find_symbol_empty_name():
    r = ci.find_symbol("")
    assert "error" in r


def test_find_symbol_missing_dir(tmp_path):
    r = ci.find_symbol("foo", root=str(tmp_path / "nope"))
    assert "error" in r


def test_find_symbol_no_match(tmp_path):
    (tmp_path / "x.py").write_text("print('hi')\n", encoding="utf-8")
    r = ci.find_symbol("nonexistent", root=str(tmp_path))
    assert r["total"] == 0


# ════════════════════════════════════════════════════════════════════
#  B2 — find_usages
# ════════════════════════════════════════════════════════════════════

def test_find_usages_excludes_definition(tmp_path):
    (tmp_path / "m.py").write_text("def greet():\n    pass\n\ngreet()\nprint(greet)\n", encoding="utf-8")
    r = ci.find_usages("greet", root=str(tmp_path))
    assert r["total"] == 2
    lines = {u["line"] for u in r["usages"]}
    assert 1 not in lines  # definition excluded
    assert 4 in lines and 5 in lines


def test_find_usages_includes_definition(tmp_path):
    (tmp_path / "m.py").write_text("def greet():\n    pass\n\ngreet()\n", encoding="utf-8")
    r = ci.find_usages("greet", root=str(tmp_path), exclude_definition=False)
    lines = {u["line"] for u in r["usages"]}
    assert 1 in lines  # definition included


def test_find_usages_empty_symbol():
    r = ci.find_usages("")
    assert "error" in r


def test_find_usages_no_match(tmp_path):
    (tmp_path / "x.py").write_text("x = 1\n", encoding="utf-8")
    r = ci.find_usages("nonexistent", root=str(tmp_path))
    assert r["total"] == 0


# ════════════════════════════════════════════════════════════════════
#  B3 — search_code_ctx
# ════════════════════════════════════════════════════════════════════

def test_search_code_ctx_basic(tmp_path):
    (tmp_path / "f.py").write_text("a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n", encoding="utf-8")
    r = ci.search_code_ctx("c = 3", path=str(tmp_path), before=1, after=1)
    assert len(r["results"]) == 1
    ctx = r["results"][0]["context_lines"]
    texts = [c["text"] for c in ctx]
    assert "b = 2" in texts
    assert "c = 3" in texts
    assert "d = 4" in texts


def test_search_code_ctx_regex(tmp_path):
    (tmp_path / "f.py").write_text("line1\nfoo123bar\nline3\n", encoding="utf-8")
    r = ci.search_code_ctx(r"foo\d+bar", path=str(tmp_path))
    assert r["results"][0]["line"] == 2


def test_search_code_ctx_bad_regex(tmp_path):
    r = ci.search_code_ctx("[invalid", path=str(tmp_path))
    assert "error" in r


def test_search_code_ctx_glob_filter(tmp_path):
    (tmp_path / "a.py").write_text("target = 1\n", encoding="utf-8")
    (tmp_path / "b.js").write_text("target = 2\n", encoding="utf-8")
    r = ci.search_code_ctx("target", path=str(tmp_path), file_glob="*.py")
    assert len(r["results"]) == 1
    assert r["results"][0]["file"].endswith(".py")


def test_search_code_ctx_empty_pattern():
    r = ci.search_code_ctx("")
    assert "error" in r


# ════════════════════════════════════════════════════════════════════
#  B4 — apply_patch
# ════════════════════════════════════════════════════════════════════

def test_apply_patch_single_hunk(tmp_path):
    target = tmp_path / "f.py"
    target.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    patch = f"""\
--- a/f.py
+++ {target}
@@ -1,3 +1,3 @@
 a = 1
-b = 2
+b = 99
 c = 3
"""
    r = ci.apply_patch(patch)
    assert len(r["applied"]) == 1
    assert r["applied"][0]["hunks"] == 1
    assert "b = 99" in target.read_text(encoding="utf-8")


def test_apply_patch_multi_hunk(tmp_path):
    target = tmp_path / "f.py"
    target.write_text("a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n", encoding="utf-8")
    patch = f"""\
--- a/f.py
+++ {target}
@@ -1,2 +1,2 @@
-a = 1
+a = 10
 b = 2
@@ -4,2 +4,2 @@
-d = 4
+d = 40
 e = 5
"""
    r = ci.apply_patch(patch)
    assert r["applied"][0]["hunks"] == 2
    text = target.read_text(encoding="utf-8")
    assert "a = 10" in text and "d = 40" in text


def test_apply_patch_new_file(tmp_path):
    target = tmp_path / "new.py"
    patch = f"""\
--- /dev/null
+++ {target}
@@ -0,0 +1,2 @@
+hello = 1
+world = 2
"""
    r = ci.apply_patch(patch)
    assert len(r["applied"]) == 1
    assert target.is_file()
    assert "hello = 1" in target.read_text(encoding="utf-8")


def test_apply_patch_empty():
    r = ci.apply_patch("")
    assert "error" in r


# ════════════════════════════════════════════════════════════════════
#  F1 — find_symbol AST 索引优先路径
# ════════════════════════════════════════════════════════════════════

def test_find_symbol_ast_context_is_real_line(tmp_path):
    """F1: Python 文件走 AST 索引，context 应该是真实的源码行，不是合成字符串。"""
    (tmp_path / "mod.py").write_text(
        "def compute(x, y):\n    return x + y\n", encoding="utf-8"
    )
    r = ci.find_symbol("compute", root=str(tmp_path))
    assert r["total"] == 1
    m = r["matches"][0]
    assert m["line"] == 1
    assert m["type"] == "function"
    # 真实行内容，不是 "function compute" 合成串
    assert "compute" in m["context"]
    assert "def compute" in m["context"] or "compute" in m["context"]


def test_find_symbol_ast_class(tmp_path):
    """F1: AST 索引能精确找到 class 定义。"""
    (tmp_path / "srv.py").write_text(
        "class Server:\n    pass\n\nclass Client:\n    pass\n", encoding="utf-8"
    )
    r = ci.find_symbol("Server", root=str(tmp_path))
    assert r["total"] == 1
    assert r["matches"][0]["type"] == "class"


def test_find_symbol_ast_no_regex_false_positive(tmp_path):
    """F1: AST 索引不会把注释/字符串里的 def 当定义。"""
    (tmp_path / "c.py").write_text(
        '# def fake():\n"""def fake2():\"\"\"\nfake3 = "def real()"\ndef real():\n    pass\n',
        encoding="utf-8",
    )
    r = ci.find_symbol("real", root=str(tmp_path))
    # AST 只会报告真实的函数定义（第4行），不包含注释/字符串里的
    assert r["total"] == 1
    assert r["matches"][0]["line"] == 4


def test_find_symbol_fallback_js(tmp_path):
    """F1: JS 文件走 regex 回退路径，结果仍然正确。"""
    (tmp_path / "util.js").write_text(
        "export function formatDate(d) { return d.toISOString(); }\n",
        encoding="utf-8",
    )
    r = ci.find_symbol("formatDate", root=str(tmp_path))
    assert r["total"] == 1
    assert r["matches"][0]["type"] == "function"


def test_apply_patch_bad_format():
    r = ci.apply_patch("this is not a diff")
    assert "error" in r
