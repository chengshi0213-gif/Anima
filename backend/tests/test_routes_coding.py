#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_routes_coding.py — v1.2.2 A5 /init 项目分析命令单元测试 (pytest)

覆盖：
  - _detect_stack：Python(requirements.txt+pytest)/Node(package.json+react+pnpm)/未知项目
  - _read_readme：找到第一个存在的 README.* 并截断读取
  - _render_anima_md：标准模板各字段就位
  - _analyze_architecture：有 worker 用 DeepSeek-V4-Flash；出错/无 worker 时返回 ""
  - _do_init：目录不存在报错；首次生成写文件；已存在不覆盖；overwrite=true 强制覆盖
  - init_project 路由：work_dir 为空时 400

运行:
    cd E:\\AI\\workspace\\Anima\\backend
    python -m pytest tests/test_routes_coding.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import routes.coding as rc  # noqa: E402


def test_detect_stack_python(tmp_path):
    proj = tmp_path / "pyproj"
    proj.mkdir()
    (proj / "requirements.txt").write_text("fastapi\nuvicorn\npytest\n", encoding="utf-8")
    (proj / "tests").mkdir()
    (proj / "main.py").write_text("x = 1", encoding="utf-8")

    stack = rc._detect_stack(proj)
    assert stack["language"] == "Python"
    assert stack["framework"] == "FastAPI"
    assert stack["pkg_manager"] == "pip"
    assert stack["test_cmd"] == "pytest -q"
    assert stack["test_dir"] == "tests/"
    assert stack["entry"] == "main.py"


def test_detect_stack_node(tmp_path):
    proj = tmp_path / "nodeproj"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({
        "main": "index.js",
        "dependencies": {"react": "^18.0.0"},
        "scripts": {"build": "vite build", "test": "vitest", "lint": "eslint ."},
    }), encoding="utf-8")
    (proj / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    (proj / "src").mkdir()

    stack = rc._detect_stack(proj)
    assert stack["language"] == "JavaScript"
    assert stack["framework"] == "React"
    assert stack["pkg_manager"] == "pnpm"
    assert stack["build_cmd"] == "pnpm run build"
    assert stack["test_cmd"] == "pnpm test"
    assert stack["lint_cmd"] == "pnpm run lint"
    assert stack["entry"] == "index.js"
    assert stack["test_dir"] == "src/**/*.test.*"


def test_detect_stack_unknown(tmp_path):
    proj = tmp_path / "empty"
    proj.mkdir()
    stack = rc._detect_stack(proj)
    assert stack["language"] == "未知"
    assert stack["framework"] == "—"
    assert stack["build_cmd"] == "—"


def test_read_readme_found_and_capped(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "README.md").write_text("# Title\nHello world", encoding="utf-8")
    content = rc._read_readme(proj)
    assert "Hello world" in content


def test_read_readme_missing(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    assert rc._read_readme(proj) == ""


def test_render_anima_md_contains_all_sections():
    stack = {
        "language": "Python", "framework": "FastAPI", "pkg_manager": "pip",
        "build_cmd": "—", "test_cmd": "pytest -q", "lint_cmd": "—",
        "style": "—", "test_dir": "tests/", "entry": "main.py",
    }
    md = rc._render_anima_md("demo", stack, "这是一个 FastAPI 项目。")
    assert "# 项目：demo" in md
    assert "## 构建与测试" in md
    assert "`pytest -q`" in md
    assert "## 技术栈" in md
    assert "Python" in md and "FastAPI" in md
    assert "## 项目约定" in md
    assert "main.py" in md
    assert "## 架构说明" in md
    assert "这是一个 FastAPI 项目。" in md
    assert "## 已知问题 / 注意事项" in md


def test_render_anima_md_placeholder_when_no_architecture():
    stack = {k: "—" for k in (
        "language", "framework", "pkg_manager", "build_cmd", "test_cmd",
        "lint_cmd", "style", "test_dir", "entry")}
    md = rc._render_anima_md("demo", stack, "")
    assert "<AI 分析后填写>" in md


def test_analyze_architecture_no_worker():
    out = asyncio.run(rc._analyze_architecture(None, "tree", {}, "readme"))
    assert out == ""


def test_analyze_architecture_with_worker():
    class FakeWorker:
        async def _call_api(self, messages, tools=None, stream=False, override_model=None, on_delta=None):
            assert override_model == "DeepSeek-V4-Flash"
            return {"content": "  这是架构说明  "}

    out = asyncio.run(rc._analyze_architecture(FakeWorker(), "tree", {"language": "Python"}, "readme"))
    assert out == "这是架构说明"


def test_analyze_architecture_skips_on_error():
    class FakeWorker:
        async def _call_api(self, *a, **k):
            return {"error": "boom"}

    out = asyncio.run(rc._analyze_architecture(FakeWorker(), "tree", {}, ""))
    assert out == ""


def test_do_init_missing_dir(tmp_path):
    result = asyncio.run(rc._do_init(str(tmp_path / "nope")))
    assert "error" in result


def test_do_init_writes_anima_md_when_missing(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "requirements.txt").write_text("flask\n", encoding="utf-8")

    result = asyncio.run(rc._do_init(str(proj)))
    assert result["written"] is True
    assert result["stack"]["framework"] == "Flask"

    target = proj / "ANIMA.md"
    assert target.is_file()
    assert "# 项目：proj" in target.read_text(encoding="utf-8")


def test_do_init_does_not_overwrite_existing(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "ANIMA.md").write_text("# 已有内容，别动我", encoding="utf-8")

    result = asyncio.run(rc._do_init(str(proj)))
    assert result["written"] is False
    assert (proj / "ANIMA.md").read_text(encoding="utf-8") == "# 已有内容，别动我"
    # 返回的草稿内容仍然是新生成的，供前端预览
    assert "# 项目：proj" in result["content"]


def test_do_init_overwrite_true_replaces_existing(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "ANIMA.md").write_text("# 旧内容", encoding="utf-8")

    result = asyncio.run(rc._do_init(str(proj), overwrite=True))
    assert result["written"] is True
    assert "# 项目：proj" in (proj / "ANIMA.md").read_text(encoding="utf-8")


def test_init_project_handler_requires_work_dir():
    req = make_mocked_request("POST", "/agent/executor/init")
    resp = asyncio.run(rc.init_project(req))
    assert resp.status == 400


def test_register_adds_route():
    class FakeApp:
        def __init__(self):
            self.router = self
            self.posts = []
            self.gets = []

        def add_post(self, path, handler):
            self.posts.append((path, handler))

        def add_get(self, path, handler):
            self.gets.append((path, handler))

    app = FakeApp()
    rc.register(app)
    assert ("/agent/executor/init", rc.init_project) in app.posts
    assert ("/agent/executor/anima_md", rc.anima_md_get) in app.gets
    assert ("/agent/executor/anima_md", rc.anima_md_save) in app.posts


# ════════════════════════════════════════════════════════════════════
#  A6 — 读取/保存 ANIMA.md
# ════════════════════════════════════════════════════════════════════

def test_get_anima_md_missing_dir(tmp_path):
    result = rc._get_anima_md(str(tmp_path / "nope"))
    assert "error" in result


def test_get_anima_md_not_exists(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    result = rc._get_anima_md(str(proj))
    assert result["exists"] is False
    assert result["content"] == ""


def test_get_anima_md_finds_anima(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "ANIMA.md").write_text("# 项目规范", encoding="utf-8")
    result = rc._get_anima_md(str(proj))
    assert result["exists"] is True
    assert result["filename"] == "ANIMA.md"
    assert "# 项目规范" in result["content"]


def test_get_anima_md_compat_fallback(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "CLAUDE.md").write_text("CLAUDE 内容", encoding="utf-8")
    result = rc._get_anima_md(str(proj))
    assert result["exists"] is True
    assert result["filename"] == "CLAUDE.md"
    assert "CLAUDE 内容" in result["content"]


def test_save_anima_md_missing_dir(tmp_path):
    result = rc._save_anima_md(str(tmp_path / "nope"), "内容")
    assert "error" in result


def test_save_anima_md_writes_file(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    result = rc._save_anima_md(str(proj), "# 编辑后的内容")
    assert result["ok"] is True
    assert (proj / "ANIMA.md").read_text(encoding="utf-8") == "# 编辑后的内容"


def test_anima_md_get_handler_requires_work_dir():
    req = make_mocked_request("GET", "/agent/executor/anima_md")
    resp = asyncio.run(rc.anima_md_get(req))
    assert resp.status == 400


def test_anima_md_get_handler_reads_query(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "ANIMA.md").write_text("内容X", encoding="utf-8")
    req = make_mocked_request("GET", f"/agent/executor/anima_md?work_dir={proj}")
    resp = asyncio.run(rc.anima_md_get(req))
    assert resp.status == 200


def test_anima_md_save_handler_requires_work_dir():
    req = make_mocked_request("POST", "/agent/executor/anima_md")
    resp = asyncio.run(rc.anima_md_save(req))
    assert resp.status == 400
