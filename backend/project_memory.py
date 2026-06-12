#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
project_memory.py — 项目记忆系统（A1，对标 Claude Code 的 CLAUDE.md + Auto Memory）

加载优先级（低→高，先拼的在上面，后拼的更"新鲜"）：
  1. 全局用户记忆   DATA_DIR/ANIMA.md（所有项目通用）
  2. 项目共享记忆   <work_dir>/ANIMA.md（兼容 CLAUDE.md > AGENTS.md > .cursorrules，入库共享）
  3. 项目个人记忆   <work_dir>/ANIMA.local.md（不入库，写入 .gitignore）
  4. Agent 自写记忆 DATA_DIR/projects/<repo_hash>/memory/MEMORY.md（前 200 行，对标 Auto Memory）
  5. 全局规则       <work_dir>/.anima/rules/*.md 中无 paths 字段的规则

`get_scoped_rules()` 另外按 paths frontmatter 匹配，供 file_read/file_edit 后按需追加。

机器本地内容（DATA_DIR 下）不随项目仓库走；ANIMA.md/.local/.anima/ 跟随项目仓库。
"""
from __future__ import annotations

import fnmatch
import hashlib
from datetime import datetime
from pathlib import Path

from config import DATA_DIR

_MAX_FILE_CHARS = 4000          # 单个记忆文件注入上限（防止 ANIMA.md 写成小说撑爆上下文）
_MEMORY_INDEX_LINES = 200        # MEMORY.md 自动加载的行数（对标 Claude Code Auto Memory）
_MAX_MEMORY_LINES = 400          # 自动记忆超过此行数时裁剪到最近 200 行

# Claude Code / 通用标准兼容：项目共享记忆文件检测顺序
_COMPAT_NAMES = ["ANIMA.md", "CLAUDE.md", "AGENTS.md", ".cursorrules"]


def repo_hash(work_dir: str) -> str:
    """work_dir 的稳定哈希，用作 DATA_DIR/projects/<hash>/ 的目录名。"""
    resolved = str(Path(work_dir).resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def _project_memory_dir(work_dir: str) -> Path:
    d = DATA_DIR / "projects" / repo_hash(work_dir) / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_capped(path: Path, max_chars: int = _MAX_FILE_CHARS) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if len(text) > max_chars:
        return text[:max_chars] + f"\n…[截断，原文 {len(text)} 字符]"
    return text


def _read_index_lines(path: Path, n: int = _MEMORY_INDEX_LINES) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    return "\n".join(lines[:n])


def _find_project_memory_file(work_dir: Path) -> Path | None:
    """按兼容顺序找项目共享记忆文件：ANIMA.md > CLAUDE.md > AGENTS.md > .cursorrules"""
    for name in _COMPAT_NAMES:
        p = work_dir / name
        if p.is_file():
            return p
    return None


def _parse_rule_file(path: Path) -> tuple[dict, str]:
    """解析 .anima/rules/*.md 的 frontmatter（paths: [...]）+ 正文。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}, ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            import yaml
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except Exception:
                meta = {}
            return meta if isinstance(meta, dict) else {}, parts[2].strip()
    return {}, text.strip()


def _rules_dir(work_dir: Path) -> Path:
    return work_dir / ".anima" / "rules"


def _load_global_rules(work_dir: Path) -> str:
    """.anima/rules/*.md 中没有 paths 字段的规则——视为全局规则，会话开始即注入。"""
    rdir = _rules_dir(work_dir)
    if not rdir.is_dir():
        return ""
    parts = []
    for f in sorted(rdir.glob("*.md")):
        meta, body = _parse_rule_file(f)
        if not meta.get("paths") and body:
            parts.append(f"### {f.stem}\n{body}")
    if not parts:
        return ""
    return "## 全局规则（.anima/rules/）\n" + "\n\n".join(parts)


def load_project_memory(work_dir: str | None) -> str:
    """加载多层级项目记忆，拼成一段 context 文本（供注入 system/task）。
    work_dir 为空或不是目录时返回空字符串（日常房间不挂项目记忆）。
    """
    if not work_dir:
        return ""
    base = Path(work_dir)
    if not base.is_dir():
        return ""

    sections: list[str] = []

    global_md = DATA_DIR / "ANIMA.md"
    if global_md.is_file():
        content = _read_capped(global_md)
        if content.strip():
            sections.append(f"## 全局记忆（ANIMA.md，所有项目通用）\n{content}")

    proj_file = _find_project_memory_file(base)
    if proj_file:
        content = _read_capped(proj_file)
        if content.strip():
            sections.append(f"## 项目记忆（{proj_file.name}）\n{content}")

    local_md = base / "ANIMA.local.md"
    if local_md.is_file():
        content = _read_capped(local_md)
        if content.strip():
            sections.append(f"## 个人记忆（ANIMA.local.md，不入库）\n{content}")

    auto_memory = _project_memory_dir(work_dir) / "MEMORY.md"
    if auto_memory.is_file():
        content = _read_index_lines(auto_memory)
        if content.strip():
            sections.append(f"## 自动记忆（上次会话学到的）\n{content}")

    global_rules = _load_global_rules(base)
    if global_rules:
        sections.append(global_rules)

    if not sections:
        return ""
    return "\n\n# 项目记忆（自动注入）\n\n" + "\n\n".join(sections) + "\n"


def get_scoped_rules(work_dir: str, active_file: str) -> str:
    """返回 .anima/rules/*.md 中 paths 匹配 active_file 的规则正文。
    供 file_read/file_edit 调用后按需追加（省上下文，不在会话开始全量加载）。"""
    if not work_dir or not active_file:
        return ""
    base = Path(work_dir)
    rdir = _rules_dir(base)
    if not rdir.is_dir():
        return ""
    try:
        rel = str(Path(active_file).resolve().relative_to(base.resolve()))
    except Exception:
        rel = active_file
    rel = rel.replace("\\", "/")

    matched = []
    for f in sorted(rdir.glob("*.md")):
        meta, body = _parse_rule_file(f)
        paths = meta.get("paths")
        if not paths or not body:
            continue
        if isinstance(paths, str):
            paths = [paths]
        for pat in paths:
            if fnmatch.fnmatch(rel, pat):
                matched.append(f"### {f.stem}\n{body}")
                break
    if not matched:
        return ""
    return f"## 路径规则（{rel}）\n" + "\n\n".join(matched)


# ── Auto Memory（A4 读写原语）──────────────────────────────────────────────

def auto_memory_path(work_dir: str) -> Path:
    return _project_memory_dir(work_dir) / "MEMORY.md"


def read_auto_memory(work_dir: str) -> str:
    p = auto_memory_path(work_dir)
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def append_auto_memory(work_dir: str, entry: str) -> dict:
    """追加一条自动记忆条目（带日期标题）。超过 _MAX_MEMORY_LINES 行时
    只保留标题 + 最近 200 行，防止 MEMORY.md 无限增长。"""
    entry = entry.strip()
    if not entry:
        return {"ok": False, "reason": "空内容"}
    p = auto_memory_path(work_dir)
    existing = p.read_text(encoding="utf-8") if p.is_file() else "# MEMORY\n"
    stamp = datetime.now().strftime("%Y-%m-%d")
    new_content = existing.rstrip() + f"\n\n## {stamp}\n{entry}\n"
    lines = new_content.splitlines()
    if len(lines) > _MAX_MEMORY_LINES:
        lines = lines[:1] + lines[-200:]
        new_content = "\n".join(lines) + "\n"
    p.write_text(new_content, encoding="utf-8")
    return {"ok": True, "path": str(p), "lines": len(lines)}
