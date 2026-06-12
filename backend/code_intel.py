"""
code_intel.py — 代码智能工具（B1-B4，v1.2.2 Phase 2）

  B1  find_symbol      — 按语言正则模式定位符号定义（def/class/const/type…）
  B2  find_usages      — 全仓库找某符号的使用位置（可排除定义本身）
  B3  search_code_ctx  — 带上下文行的代码搜索（类似 grep -B/-A）
  B4  apply_patch      — 多 hunk unified diff 应用（安全补丁工具）

所有函数都经过 path_sandbox 护栏，与 xi_worker 的 _search_code/_read_file 同级安全。
"""
from __future__ import annotations

import re
from pathlib import Path

try:
    import path_sandbox
except ImportError:
    path_sandbox = None

_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".next", ".nuxt", "venv", ".venv",
    "env", ".env", ".tox", "target", "out", "bin", "obj",
}
_MAX_FILE_SIZE = 2_000_000

_DEF_PATTERNS: dict[str, list[str]] = {
    ".py":  [r"^\s*(def|class|async\s+def)\s+{name}\b", r"^{name}\s*="],
    ".pyi": [r"^\s*(def|class|async\s+def)\s+{name}\b", r"^{name}\s*[=:]"],
    ".ts":  [r"\b(function|class|const|let|var|interface|type|enum)\s+{name}\b",
             r"export\s+(default\s+)?(function|class|const|let|var|interface|type|enum)\s+{name}\b"],
    ".tsx": [r"\b(function|class|const|let|var|interface|type|enum)\s+{name}\b",
             r"export\s+(default\s+)?(function|class|const|let|var|interface|type|enum)\s+{name}\b"],
    ".js":  [r"\b(function|class|const|let|var)\s+{name}\b",
             r"export\s+(default\s+)?(function|class|const|let|var)\s+{name}\b"],
    ".jsx": [r"\b(function|class|const|let|var)\s+{name}\b"],
    ".go":  [r"\b(func)\s+{name}\b", r"\b(func)\s+\(.*?\)\s+{name}\b",
             r"\b(type)\s+{name}\b", r"\b(var)\s+{name}\b", r"\b{name}\s*:?="],
    ".rs":  [r"\b(fn|struct|enum|trait|type|const|static|impl)\s+{name}\b"],
    ".java": [r"\b(class|interface|enum)\s+{name}\b",
              r"(public|private|protected|static|final|\s)+\S+\s+{name}\s*\("],
    ".rb":  [r"^\s*(def|class|module)\s+{name}\b"],
    ".c":   [r"\b\w[\w\s\*]*\s+{name}\s*\("],
    ".h":   [r"\b\w[\w\s\*]*\s+{name}\s*\(", r"#define\s+{name}\b"],
    ".cpp": [r"\b\w[\w\s\*:]*\s+{name}\s*\(", r"class\s+{name}\b"],
}


def _safe_check(path: str) -> bool:
    if path_sandbox is None:
        return True
    try:
        ok, _ = path_sandbox.check_path(path, write=False)
        return ok
    except Exception:
        return True


def _walk_files(root: Path, file_glob: str | None = None, limit: int = 5000):
    """递归遍历代码文件，跳过噪声目录和大文件。"""
    stack = [root]
    count = 0
    while stack and count < limit:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name)
        except Exception:
            continue
        for item in entries:
            if item.is_dir():
                if item.name not in _SKIP_DIRS:
                    stack.append(item)
                continue
            if not item.is_file():
                continue
            if file_glob and not item.match(file_glob):
                continue
            try:
                if item.stat().st_size > _MAX_FILE_SIZE:
                    continue
            except Exception:
                continue
            if not _safe_check(str(item)):
                continue
            count += 1
            yield item


# ── B1: find_symbol ──────────────────────────────────────────────

def find_symbol(name: str, symbol_type: str = "any", root: str = ".") -> dict:
    """在代码库中找符号定义位置。
    symbol_type: function | class | variable | any
    返回: {matches: [{file, line, type, context}], total}
    """
    if not name or not name.strip():
        return {"error": "name 不能为空"}
    name = name.strip()
    base = Path(root)
    if not base.is_dir():
        return {"error": f"目录不存在: {root}"}

    matches = []
    for fpath in _walk_files(base):
        ext = fpath.suffix.lower()
        patterns = _DEF_PATTERNS.get(ext)
        if not patterns:
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat_tmpl in patterns:
                pat = pat_tmpl.format(name=re.escape(name))
                m = re.search(pat, line)
                if not m:
                    continue
                kw = m.group(1) if m.lastindex else ""
                sym_type = _classify_keyword(kw, ext)
                if symbol_type != "any" and sym_type != symbol_type:
                    continue
                matches.append({
                    "file": str(fpath), "line": i,
                    "type": sym_type, "context": line.strip()[:200],
                })
                break
        if len(matches) >= 50:
            break
    return {"matches": matches, "total": len(matches)}


def _classify_keyword(kw: str, ext: str) -> str:
    kw = kw.strip().lower()
    if kw in ("def", "async def", "fn", "func", "function"):
        return "function"
    if kw in ("class", "struct", "trait", "impl", "interface", "enum", "module"):
        return "class"
    if kw in ("const", "let", "var", "static", "type"):
        return "variable"
    return "variable"


# ── B2: find_usages ──────────────────────────────────────────────

def find_usages(symbol: str, root: str = ".",
                exclude_definition: bool = True, limit: int = 50) -> dict:
    """找某个符号在代码库中的所有使用位置。
    exclude_definition=True 时过滤掉定义行本身。
    返回: {usages: [{file, line, context}], total}
    """
    if not symbol or not symbol.strip():
        return {"error": "symbol 不能为空"}
    symbol = symbol.strip()
    base = Path(root)
    if not base.is_dir():
        return {"error": f"目录不存在: {root}"}

    defs = set()
    if exclude_definition:
        defs_result = find_symbol(symbol, root=root)
        for m in defs_result.get("matches", []):
            defs.add((m["file"], m["line"]))

    usages = []
    pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
    for fpath in _walk_files(base):
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        fp = str(fpath)
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                if exclude_definition and (fp, i) in defs:
                    continue
                usages.append({"file": fp, "line": i, "context": line.strip()[:200]})
                if len(usages) >= limit:
                    return {"usages": usages, "total": len(usages), "truncated": True}
    return {"usages": usages, "total": len(usages), "truncated": False}


# ── B3: search_code_ctx ─────────────────────────────────────────

def search_code_ctx(pattern: str, path: str = ".", file_glob: str = "*",
                    before: int = 2, after: int = 2, limit: int = 30) -> dict:
    """带上下文行的代码搜索（类似 grep -B/-A -C）。
    返回: {results: [{file, line, context_lines: [{n, text}], match}], truncated}
    """
    if not pattern:
        return {"error": "pattern 不能为空"}
    base = Path(path)
    if not base.is_dir():
        return {"error": f"目录不存在: {path}"}

    try:
        rx = re.compile(pattern)
    except re.error as e:
        return {"error": f"正则错误: {e}"}

    before = max(0, min(before, 10))
    after = max(0, min(after, 10))
    results = []
    g = file_glob if file_glob != "*" else None
    for fpath in _walk_files(base, file_glob=g):
        try:
            lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines):
            if rx.search(line):
                start = max(0, i - before)
                end = min(len(lines), i + after + 1)
                ctx = [{"n": start + j + 1, "text": lines[start + j][:200]}
                       for j in range(end - start)]
                results.append({
                    "file": str(fpath), "line": i + 1,
                    "match": line.strip()[:200], "context_lines": ctx,
                })
                if len(results) >= limit:
                    return {"results": results, "truncated": True}
    return {"results": results, "truncated": False}


# ── B4: apply_patch ──────────────────────────────────────────────

def apply_patch(patch: str) -> dict:
    """应用 unified diff 格式补丁（多 hunk 多文件支持）。
    返回: {applied: [{file, hunks}], errors: [...]}
    """
    if not patch or not patch.strip():
        return {"error": "patch 不能为空"}

    hunks = _parse_unified_diff(patch)
    if "error" in hunks:
        return hunks

    applied = []
    errors = []
    for file_path, file_hunks in hunks["files"].items():
        if not _safe_check(file_path):
            errors.append(f"护栏拒绝: {file_path}")
            continue
        try:
            p = Path(file_path)
            if p.is_file():
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            else:
                lines = []
            lines = _apply_hunks(lines, file_hunks)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("".join(lines), encoding="utf-8")
            applied.append({"file": file_path, "hunks": len(file_hunks)})
        except Exception as e:
            errors.append(f"{file_path}: {e}")
    return {"applied": applied, "errors": errors}


def _parse_unified_diff(text: str) -> dict:
    """解析多文件 unified diff，返回 {files: {path: [hunks]}}。"""
    files: dict[str, list] = {}
    current_file = None
    current_hunk = None
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        if line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            current_file = path
            files.setdefault(current_file, [])
            continue
        if line.startswith("@@ "):
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if not m:
                return {"error": f"无法解析 hunk 头: {line}"}
            current_hunk = {
                "old_start": int(m.group(1)), "old_count": int(m.group(2) or 1),
                "new_start": int(m.group(3)), "new_count": int(m.group(4) or 1),
                "lines": [],
            }
            if current_file is not None:
                files[current_file].append(current_hunk)
            continue
        if current_hunk is not None:
            if line.startswith("+") or line.startswith("-") or line.startswith(" ") or line == "":
                current_hunk["lines"].append(raw_line if raw_line.endswith("\n") else raw_line + "\n")
    if not files:
        return {"error": "未找到有效的 diff 内容"}
    return {"files": files}


def _apply_hunks(lines: list[str], hunks: list[dict]) -> list[str]:
    """倒序应用 hunks（避免行号偏移）。"""
    for hunk in reversed(hunks):
        start = hunk["old_start"] - 1
        old_count = hunk["old_count"]
        new_lines = []
        for hl in hunk["lines"]:
            if hl.startswith("+"):
                new_lines.append(hl[1:])
            elif hl.startswith(" "):
                new_lines.append(hl[1:])
        lines[start:start + old_count] = new_lines
    return lines


# ── Tool definitions for B5 registration ────────────────────────

FIND_SYMBOL_DEF = {
    "type": "function",
    "function": {
        "name": "find_symbol",
        "description": "在代码库中按名字查找符号定义位置（def/class/const/type…）。按语言自动选择匹配模式，返回文件路径、行号和上下文。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "要查找的符号名"},
                "symbol_type": {"type": "string", "enum": ["any", "function", "class", "variable"],
                                "description": "符号类型过滤，默认 any"},
                "root": {"type": "string", "description": "搜索根目录，默认 '.'"},
            },
            "required": ["name"],
        },
    },
}

FIND_USAGES_DEF = {
    "type": "function",
    "function": {
        "name": "find_usages",
        "description": "在代码库中查找某个符号的所有使用位置。默认排除定义行本身，只返回引用。",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "要查找的符号名"},
                "root": {"type": "string", "description": "搜索根目录，默认 '.'"},
                "exclude_definition": {"type": "boolean", "description": "是否排除定义本身，默认 true"},
            },
            "required": ["symbol"],
        },
    },
}

SEARCH_CODE_CTX_DEF = {
    "type": "function",
    "function": {
        "name": "search_code_ctx",
        "description": "带上下文行的代码搜索（类似 grep -B/-A）。支持正则，返回匹配行及其前后各 N 行。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "正则表达式模式"},
                "path": {"type": "string", "description": "搜索目录，默认 '.'"},
                "file_glob": {"type": "string", "description": "文件名 glob 过滤，默认 '*'"},
                "before": {"type": "integer", "description": "匹配行前显示行数，默认 2"},
                "after": {"type": "integer", "description": "匹配行后显示行数，默认 2"},
            },
            "required": ["pattern"],
        },
    },
}

APPLY_PATCH_DEF = {
    "type": "function",
    "function": {
        "name": "apply_patch",
        "description": "应用 unified diff 格式补丁（多 hunk 多文件支持）。适合一次性修改多处代码。",
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {"type": "string", "description": "unified diff 格式补丁文本"},
            },
            "required": ["patch"],
        },
    },
}

CODE_INTEL_TOOL_DEFS = [FIND_SYMBOL_DEF, FIND_USAGES_DEF, SEARCH_CODE_CTX_DEF, APPLY_PATCH_DEF]

CODE_INTEL_DISPATCH = {
    "find_symbol": lambda **kw: find_symbol(kw["name"], kw.get("symbol_type", "any"), kw.get("root", ".")),
    "find_usages": lambda **kw: find_usages(kw["symbol"], kw.get("root", "."), kw.get("exclude_definition", True)),
    "search_code_ctx": lambda **kw: search_code_ctx(
        kw["pattern"], kw.get("path", "."), kw.get("file_glob", "*"),
        kw.get("before", 2), kw.get("after", 2)),
    "apply_patch": lambda **kw: apply_patch(kw["patch"]),
}
