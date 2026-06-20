"""
routes/coding.py — A5: /init 项目分析命令（生成 ANIMA.md）

  POST /agent/executor/init   {work_dir, overwrite?}
    1. map_project(work_dir) 拿目录树
    2. 按 package.json/requirements.txt/Cargo.toml/go.mod 等检测技术栈与构建/测试命令
    3. 读 README 片段
    4. 用 executor worker 的 DeepSeek-V4-Flash 轻量分析架构说明
    5. 套用标准模板拼出 ANIMA.md；已存在且未传 overwrite=true 时不覆盖，只返回草稿
    6. 返回 {content, path, written, stack} 供前端预览/编辑（A6）
"""
from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web

from .auth import CORS_HEADERS
from xi_worker import _map_project, _read_file, _write_file
from project_memory import _find_project_memory_file

_FRAMEWORK_BY_DEP = (
    ("next", "Next.js"), ("nuxt", "Nuxt"), ("react", "React"), ("vue", "Vue"),
    ("svelte", "Svelte"), ("express", "Express"), ("fastify", "Fastify"),
)
_FRAMEWORK_BY_PY_DEP = (
    ("fastapi", "FastAPI"), ("flask", "Flask"), ("django", "Django"), ("aiohttp", "aiohttp"),
)


def _detect_stack(base: Path) -> dict:
    """看常见配置文件猜技术栈/包管理/构建测试命令，未知字段留 '—'。"""
    stack = {
        "language": "未知", "framework": "—", "pkg_manager": "—",
        "build_cmd": "—", "test_cmd": "—", "lint_cmd": "—",
        "style": "—", "test_dir": "—", "entry": "—",
    }

    pkg_json = base / "package.json"
    if pkg_json.is_file():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            data = {}
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        stack["language"] = "TypeScript" if (base / "tsconfig.json").is_file() else "JavaScript"
        for dep, label in _FRAMEWORK_BY_DEP:
            if dep in deps:
                stack["framework"] = label
                break
        if (base / "pnpm-lock.yaml").is_file():
            stack["pkg_manager"] = "pnpm"
        elif (base / "yarn.lock").is_file():
            stack["pkg_manager"] = "yarn"
        else:
            stack["pkg_manager"] = "npm"
        scripts = data.get("scripts", {})
        if "build" in scripts:
            stack["build_cmd"] = f"{stack['pkg_manager']} run build"
        if "test" in scripts:
            stack["test_cmd"] = f"{stack['pkg_manager']} test"
        if "lint" in scripts:
            stack["lint_cmd"] = f"{stack['pkg_manager']} run lint"
        elif "typecheck" in scripts:
            stack["lint_cmd"] = f"{stack['pkg_manager']} run typecheck"
        stack["entry"] = data.get("main") or "—"
        if (base / "src").is_dir():
            stack["test_dir"] = "src/**/*.test.*"
        return stack

    if (base / "Cargo.toml").is_file():
        stack.update({
            "language": "Rust", "pkg_manager": "cargo",
            "build_cmd": "cargo build", "test_cmd": "cargo test", "lint_cmd": "cargo clippy",
            "entry": "src/main.rs", "test_dir": "tests/ + #[cfg(test)]",
        })
        return stack

    if (base / "go.mod").is_file():
        stack.update({
            "language": "Go", "pkg_manager": "go modules",
            "build_cmd": "go build ./...", "test_cmd": "go test ./...", "lint_cmd": "go vet ./...",
            "entry": "main.go", "test_dir": "*_test.go",
        })
        return stack

    if (base / "pyproject.toml").is_file() or (base / "requirements.txt").is_file() \
            or (base / "setup.py").is_file():
        stack["language"] = "Python"
        text = ""
        for name in ("requirements.txt", "pyproject.toml"):
            p = base / name
            if p.is_file():
                text += p.read_text(encoding="utf-8", errors="replace").lower()
        stack["pkg_manager"] = "poetry" if "[tool.poetry]" in text else "pip"
        for dep, label in _FRAMEWORK_BY_PY_DEP:
            if dep in text:
                stack["framework"] = label
                break
        if (base / "pytest.ini").is_file() or (base / "tests").is_dir() or "pytest" in text:
            stack["test_cmd"] = "pytest -q"
            stack["test_dir"] = "tests/"
        for entry_name in ("main.py", "app.py", "__main__.py"):
            if (base / entry_name).is_file():
                stack["entry"] = entry_name
                break
        return stack

    return stack


def _read_readme(base: Path) -> str:
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = base / name
        if p.is_file():
            result = _read_file(str(p), limit=120)
            return result.get("content", "")
    return ""


async def _analyze_architecture(worker, tree: str, stack: dict, readme: str) -> str:
    """用轻量模型把目录树+技术栈+README 概括成 2-4 句架构说明；无 worker 或出错时返回空。"""
    if worker is None:
        return ""
    prompt = (
        "根据以下项目目录结构、检测到的技术栈和 README 片段，"
        "用 2-4 句中文概括这个项目的架构（核心模块、数据流向、关键设计），"
        "供后续 AI 协作者快速建立认知。直接输出正文，不要标题、不要客套话。\n\n"
        f"## 技术栈\n{json.dumps(stack, ensure_ascii=False)}\n\n"
        f"## 目录结构\n{tree[:2000]}\n\n"
        f"## README 片段\n{readme[:1500]}\n"
    )
    try:
        resp = await worker._call_api(
            [{"role": "user", "content": prompt}], tools=None, stream=False,
            override_model="DeepSeek-V4-Flash",
        )
    except Exception:
        return ""
    if "error" in resp:
        return ""
    return (resp.get("content") or "").strip()


def _render_anima_md(name: str, stack: dict, architecture: str) -> str:
    arch = architecture or "<AI 分析后填写>"
    return (
        f"# 项目：{name}\n\n"
        "## 构建与测试\n"
        f"- 构建：`{stack['build_cmd']}`\n"
        f"- 测试：`{stack['test_cmd']}`\n"
        f"- 类型检查：`{stack['lint_cmd']}`\n\n"
        "## 技术栈\n"
        f"- 语言：{stack['language']}\n"
        f"- 框架：{stack['framework']}\n"
        f"- 包管理：{stack['pkg_manager']}\n\n"
        "## 项目约定\n"
        f"- 代码风格：{stack['style']}\n"
        f"- 测试位置：{stack['test_dir']}\n"
        f"- 主入口：{stack['entry']}\n\n"
        "## 架构说明\n"
        f"{arch}\n\n"
        "## 已知问题 / 注意事项\n"
        "<留空，Agent 运行中更新>\n"
    )


async def _do_init(work_dir: str, overwrite: bool = False, worker=None) -> dict:
    base = Path(work_dir)
    if not base.is_dir():
        return {"error": f"目录不存在: {work_dir}"}

    tree_info = _map_project(work_dir, max_depth=2)
    if "error" in tree_info:
        return tree_info

    stack = _detect_stack(base)
    readme = _read_readme(base)
    architecture = await _analyze_architecture(worker, tree_info.get("tree", ""), stack, readme)
    content = _render_anima_md(base.name, stack, architecture)

    target = base / "ANIMA.md"
    written = False
    if overwrite or not target.is_file():
        write_result = _write_file(str(target), content)
        if "error" in write_result:
            return write_result
        written = True

    return {"content": content, "path": str(target), "written": written, "stack": stack}


async def init_project(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    work_dir = (body.get("work_dir") or "").strip()
    if not work_dir:
        return web.json_response({"error": "work_dir 不能为空"}, status=400, headers=CORS_HEADERS)

    servers = request.app.get("servers", {})
    server = servers.get("executor")
    worker = server.worker if server else None

    result = await _do_init(work_dir, overwrite=bool(body.get("overwrite")), worker=worker)
    status = 400 if "error" in result else 200
    return web.json_response(result, status=status, headers=CORS_HEADERS)


def _get_anima_md(work_dir: str) -> dict:
    """A6: 读取当前项目记忆文件供前端展示/编辑。
    按 A1 兼容顺序找 ANIMA.md > CLAUDE.md > AGENTS.md > .cursorrules；不存在则 exists=False。"""
    base = Path(work_dir)
    if not base.is_dir():
        return {"error": f"目录不存在: {work_dir}"}

    found = _find_project_memory_file(base)
    if not found:
        return {"exists": False, "content": "", "filename": None, "path": None}

    result = _read_file(str(found), limit=10000)
    if "error" in result:
        return result
    return {"exists": True, "content": result.get("content", ""),
            "filename": found.name, "path": str(found)}


def _save_anima_md(work_dir: str, content: str) -> dict:
    """A6: 保存编辑后的 ANIMA.md。
    始终写入 <work_dir>/ANIMA.md（A1 优先级最高，覆盖式编辑落到这个文件最直观）。"""
    base = Path(work_dir)
    if not base.is_dir():
        return {"error": f"目录不存在: {work_dir}"}

    target = base / "ANIMA.md"
    result = _write_file(str(target), content)
    if "error" in result:
        return result
    return {"ok": True, "path": str(target)}


async def anima_md_get(request):
    work_dir = (request.query.get("work_dir") or "").strip()
    if not work_dir:
        return web.json_response({"error": "work_dir 不能为空"}, status=400, headers=CORS_HEADERS)
    result = _get_anima_md(work_dir)
    status = 400 if "error" in result else 200
    return web.json_response(result, status=status, headers=CORS_HEADERS)


async def anima_md_save(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    work_dir = (body.get("work_dir") or "").strip()
    if not work_dir:
        return web.json_response({"error": "work_dir 不能为空"}, status=400, headers=CORS_HEADERS)
    result = _save_anima_md(work_dir, body.get("content", ""))
    status = 400 if "error" in result else 200
    return web.json_response(result, status=status, headers=CORS_HEADERS)


def register(app):
    app.router.add_post("/agent/executor/init", init_project)
    app.router.add_get("/agent/executor/anima_md", anima_md_get)
    app.router.add_post("/agent/executor/anima_md", anima_md_save)
