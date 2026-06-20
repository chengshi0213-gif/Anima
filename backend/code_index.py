#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
code_index.py — Phase L 代码定位层（v1.3）

三个能力：
  1. 持久符号索引（SHA256 增量缓存，只重扫改过的文件）
  2. find_symbol_ast — Python 文件用 ast 精确定位（无歧义），其他语言 regex 回退
  3. locate_relevant — 给任务描述/符号名，返回最相关文件列表（TF-IDF 式评分）

设计约束：
  - 零外部依赖（stdlib: ast, hashlib, json, pathlib, re）
  - 无文件数硬上限（replaces _walk_files(limit=5000)）
  - 索引持久化到 DATA_DIR/.anima_index/code_index_{project_hash}.json
  - 线程安全：读多写少，索引重建是单次操作
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

try:
    from config import get_config
    _DATA_DIR = Path(get_config().get("paths", {}).get("data_dir", ".") or ".")
except Exception:
    _DATA_DIR = Path(".")

_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".next", ".nuxt", "venv", ".venv",
    "env", ".env", ".tox", "target", "out", "bin", "obj", "tmp", "temp",
    ".ruff_cache", ".hypothesis",
}
_INDEX_EXTS = {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".go",
               ".rs", ".java", ".rb", ".c", ".h", ".cpp"}
_MAX_FILE_BYTES = 2_000_000


# ── データstructures ─────────────────────────────────────────────────────────

@dataclass
class SymbolEntry:
    name: str
    kind: str    # function / class / variable / import
    line: int


@dataclass
class FileEntry:
    rel: str                          # 相对于 root 的路径
    sha256: str
    symbols: list[SymbolEntry] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)   # imported module names
    size: int = 0

    def symbol_names(self) -> set[str]:
        return {s.name for s in self.symbols}


# ── SHA256 工具 ─────────────────────────────────────────────────────────────

def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _index_path(root: Path) -> Path:
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:12]
    # 收归专用缓存目录，避免索引文件糊在仓库根（R3）
    return _DATA_DIR / ".anima_index" / f"code_index_{key}.json"


# ── 文件遍历（无上限）──────────────────────────────────────────────────────

def _iter_files(root: Path):
    """递归遍历 root，跳过噪声目录和大文件，无文件数上限。"""
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name)
        except Exception:
            continue
        for item in entries:
            if item.is_dir():
                if item.name not in _SKIP_DIRS and not item.name.startswith("."):
                    stack.append(item)
                continue
            if not item.is_file():
                continue
            if item.suffix.lower() not in _INDEX_EXTS:
                continue
            try:
                if item.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield item


# ── Python AST 索引 ──────────────────────────────────────────────────────────

def _index_python(path: Path, root: Path) -> FileEntry:
    """用 ast 模块精确提取 Python 文件的符号和导入（无歧义，无误报）。"""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(path))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return _index_fallback(path, root)

    symbols: list[SymbolEntry] = []
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(SymbolEntry(node.name, "function", node.lineno))
        elif isinstance(node, ast.ClassDef):
            symbols.append(SymbolEntry(node.name, "class", node.lineno))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == t.id.upper() or \
                   (isinstance(t, ast.Name) and isinstance(node.value, (ast.Constant, ast.List, ast.Dict))):
                    symbols.append(SymbolEntry(t.id, "variable", node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module.split(".")[0])

    rel = str(path.relative_to(root))
    return FileEntry(
        rel=rel,
        sha256=_file_sha256(path),
        symbols=symbols,
        imports=list(dict.fromkeys(imports)),  # 去重保序
        size=path.stat().st_size,
    )


# ── 正则回退索引（非 Python）────────────────────────────────────────────────

_REGEX_PATTERNS: dict[str, list[tuple[str, str]]] = {
    ".ts":  [
        (r"(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
        (r"(?:export\s+)?class\s+(\w+)", "class"),
        (r"(?:export\s+)?(?:const|let|var)\s+(\w+)", "variable"),
        (r"(?:export\s+)?(?:interface|type)\s+(\w+)", "class"),
    ],
    ".js":  [
        (r"(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
        (r"(?:export\s+)?class\s+(\w+)", "class"),
        (r"(?:export\s+)?(?:const|let|var)\s+(\w+)", "variable"),
    ],
    ".go":  [
        (r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(", "function"),
        (r"^type\s+(\w+)\s+(?:struct|interface)", "class"),
    ],
    ".rs":  [
        (r"^(?:pub\s+)?fn\s+(\w+)", "function"),
        (r"^(?:pub\s+)?(?:struct|enum|trait)\s+(\w+)", "class"),
    ],
    ".java": [
        (r"(?:public|private|protected|static|\s)+\w[\w<>[\]]*\s+(\w+)\s*\(", "function"),
        (r"(?:public|abstract\s+)?class\s+(\w+)", "class"),
    ],
}
_REGEX_PATTERNS[".tsx"] = _REGEX_PATTERNS[".ts"]
_REGEX_PATTERNS[".jsx"] = _REGEX_PATTERNS[".js"]
_REGEX_PATTERNS[".pyi"] = []   # 用 Python AST 处理


def _index_fallback(path: Path, root: Path) -> FileEntry:
    """正则回退：用于非 Python 文件或 Python 语法错误文件。"""
    ext = path.suffix.lower()
    patterns = _REGEX_PATTERNS.get(ext, [])
    symbols: list[SymbolEntry] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for i, line in enumerate(lines, 1):
        for pat, kind in patterns:
            m = re.search(pat, line)
            if m:
                name = m.group(1)
                if name and len(name) > 1:
                    symbols.append(SymbolEntry(name, kind, i))
                break
    rel = str(path.relative_to(root))
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return FileEntry(rel=rel, sha256=_file_sha256(path),
                     symbols=symbols, imports=[], size=size)


# ── 增量索引构建 ──────────────────────────────────────────────────────────────

def _load_cached(root: Path) -> dict[str, dict]:
    """加载已有索引，返回 {rel_path: raw_dict}。"""
    idx_path = _index_path(root)
    try:
        raw = json.loads(idx_path.read_text(encoding="utf-8"))
        if raw.get("root") == str(root.resolve()) and raw.get("version") == 2:
            return {f["rel"]: f for f in raw.get("files", [])}
    except Exception:
        pass
    return {}


def _save_index(root: Path, entries: dict[str, FileEntry]) -> None:
    idx_path = _index_path(root)
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 2,
        "root": str(root.resolve()),
        "built_at": time.time(),
        "files": [
            {**asdict(e), "symbols": [asdict(s) for s in e.symbols]}
            for e in entries.values()
        ],
    }
    idx_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def build_index(root: str | Path, force: bool = False) -> dict[str, FileEntry]:
    """增量构建/刷新索引。
    - 只重扫 SHA256 变化的文件（首次扫全量）
    - 返回完整 {rel_path: FileEntry}
    """
    root = Path(root).resolve()
    cached: dict[str, dict] = {} if force else _load_cached(root)
    entries: dict[str, FileEntry] = {}
    changed = 0

    for fpath in _iter_files(root):
        rel = str(fpath.relative_to(root))
        sha = _file_sha256(fpath)
        if not force and rel in cached and cached[rel].get("sha256") == sha:
            # 文件未变 → 直接复用缓存
            c = cached[rel]
            entries[rel] = FileEntry(
                rel=rel, sha256=sha,
                symbols=[SymbolEntry(**s) for s in c.get("symbols", [])],
                imports=c.get("imports", []),
                size=c.get("size", 0),
            )
        else:
            # 新文件或已改 → 重新索引
            if fpath.suffix.lower() in (".py", ".pyi"):
                entry = _index_python(fpath, root)
            else:
                entry = _index_fallback(fpath, root)
            entries[rel] = entry
            changed += 1

    _save_index(root, entries)
    return entries


def get_index(root: str | Path) -> dict[str, FileEntry]:
    """获取索引（缓存命中直接返回，否则增量构建）。"""
    root = Path(root).resolve()
    cached = _load_cached(root)
    if cached:
        entries: dict[str, FileEntry] = {}
        for rel, c in cached.items():
            entries[rel] = FileEntry(
                rel=rel, sha256=c.get("sha256", ""),
                symbols=[SymbolEntry(**s) for s in c.get("symbols", [])],
                imports=c.get("imports", []),
                size=c.get("size", 0),
            )
        return entries
    return build_index(root)


# ── locate_relevant ──────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """把查询/路径拆成小写 token（下划线/驼峰拆分 + 路径分隔符拆分）。"""
    text = re.sub(r"([a-z])([A-Z])", r"\1_\2", text)
    return [t.lower() for t in re.split(r"[^a-zA-Z0-9]+", text) if len(t) > 1]


def locate_relevant(query: str, root: str | Path,
                    top_k: int = 8,
                    rebuild: bool = False) -> list[dict]:
    """根据任务描述/关键词，返回最相关的文件列表（带评分理由）。

    评分策略（越高越相关）：
      +3  文件中有符号名完全匹配 query token
      +2  文件路径包含 query token
      +1  文件导入了 query token 所指的模块
      ×0.5 测试文件降权（test_ 开头）

    返回: [{rel, score, reason, symbols_matched}]，按 score 降序，最多 top_k 条。
    """
    root = Path(root).resolve()
    index = build_index(root, force=rebuild) if rebuild else get_index(root)
    if not index:
        index = build_index(root)

    query_tokens = set(_tokenize(query))
    # 也把 query 本身当 token 加进来（处理 "verify_gate" 整体查询）
    query_tokens |= {query.lower().strip(), *re.split(r"\s+", query.lower().strip())}
    query_tokens.discard("")
    if not query_tokens:
        return []

    results = []
    for rel, entry in index.items():
        score = 0.0
        reasons = []
        sym_names = entry.symbol_names()
        path_tokens = set(_tokenize(rel))

        # 符号名命中：整体名匹配 OR 符号名 token 和查询 token 有交集
        sym_hit_names = []
        for sname in sym_names:
            sname_lower = sname.lower()
            sname_tokens = set(_tokenize(sname))
            if sname_lower in query_tokens or (sname_tokens & query_tokens):
                sym_hit_names.append(sname)
        if sym_hit_names:
            score += 3 * len(sym_hit_names)
            reasons.append(f"符号命中: {', '.join(sym_hit_names[:5])}")

        # 路径 token 命中
        path_hits = query_tokens & path_tokens
        if path_hits:
            score += 2 * len(path_hits)
            reasons.append(f"路径命中: {', '.join(sorted(path_hits)[:5])}")

        # 导入命中
        import_hits = query_tokens & {i.lower() for i in entry.imports}
        if import_hits:
            score += 1 * len(import_hits)
            reasons.append(f"导入命中: {', '.join(sorted(import_hits)[:5])}")

        if score <= 0:
            continue

        # 测试文件降权（纯测试文件不是要改的目标）
        base = Path(rel).name
        if base.startswith("test_") or base.endswith("_test.py"):
            score *= 0.5

        matched_syms = sym_hit_names
        results.append({
            "rel": rel,
            "score": round(score, 2),
            "reason": "; ".join(reasons),
            "symbols_matched": matched_syms[:10],
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


# ── find_symbol_ast（B1 升级版）────────────────────────────────────────────

def find_symbol_ast(name: str, root: str | Path,
                    symbol_type: str = "any",
                    rebuild: bool = False) -> dict:
    """用索引精确查找符号定义。Python 文件通过 AST 建立，无误报。
    相比 code_intel.find_symbol：无文件数上限，Python 不依赖 regex。
    """
    if not name or not name.strip():
        return {"error": "name 不能为空"}
    root = Path(root).resolve()
    index = build_index(root, force=rebuild) if rebuild else get_index(root)
    if not index:
        index = build_index(root)

    name = name.strip()
    name_lower = name.lower()
    matches = []
    for rel, entry in sorted(index.items()):
        for sym in entry.symbols:
            if sym.name == name or sym.name.lower() == name_lower:
                if symbol_type != "any" and sym.kind != symbol_type:
                    continue
                matches.append({
                    "file": rel,
                    "line": sym.line,
                    "type": sym.kind,
                    "context": f"{sym.kind} {sym.name}",
                })
    return {"matches": matches, "total": len(matches)}


# ── 工具定义（供 executor 注册）───────────────────────────────────────────────

LOCATE_RELEVANT_DEF = {
    "type": "function",
    "function": {
        "name": "locate_relevant",
        "description": (
            "根据任务描述或关键词，在代码库中找出最相关的文件列表（基于符号名/路径/导入三维评分）。"
            "适合「我要改 X 功能，先找哪些文件」的场景，比 search_code 更快、更有方向感。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "任务描述或关键词，如「verify gate」「用户权限 permission」"},
                "root":  {"type": "string", "description": "搜索根目录，默认 '.'"},
                "top_k": {"type": "integer", "description": "返回最多 N 个文件，默认 8"},
            },
            "required": ["query"],
        },
    },
}

FIND_SYMBOL_AST_DEF = {
    "type": "function",
    "function": {
        "name": "find_symbol_ast",
        "description": (
            "用 AST 精确定位符号定义（Python 文件无歧义，其他语言 regex 回退）。"
            "比 find_symbol 更准，且无文件数上限。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name":        {"type": "string", "description": "符号名"},
                "root":        {"type": "string", "description": "搜索根目录，默认 '.'"},
                "symbol_type": {"type": "string", "enum": ["any", "function", "class", "variable"],
                                "description": "类型过滤"},
            },
            "required": ["name"],
        },
    },
}

REBUILD_INDEX_DEF = {
    "type": "function",
    "function": {
        "name": "rebuild_index",
        "description": "强制重建代码索引（正常用不到；文件大量变更后或索引疑似脏时调用）。",
        "parameters": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "要重建的项目根目录"},
            },
            "required": ["root"],
        },
    },
}

CODE_INDEX_TOOL_DEFS = [LOCATE_RELEVANT_DEF, FIND_SYMBOL_AST_DEF, REBUILD_INDEX_DEF]

CODE_INDEX_DISPATCH = {
    "locate_relevant": lambda **kw: {
        "results": locate_relevant(kw["query"], kw.get("root", "."), kw.get("top_k", 8))
    },
    "find_symbol_ast": lambda **kw: find_symbol_ast(
        kw["name"], kw.get("root", "."), kw.get("symbol_type", "any")),
    "rebuild_index": lambda **kw: {
        "files_indexed": len(build_index(kw.get("root", "."), force=True))
    },
}
