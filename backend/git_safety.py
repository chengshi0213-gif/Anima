#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
git_safety.py — 工程改动的"安全网"（M9）

商用底线：executor 在用户真实代码库上做多文件改动前，先打一个**非破坏性**快照；
万一改崩了，可以一键回滚到改之前的状态，绝不毁掉用户的商业代码。

设计要点
--------
1. **快照零破坏**：对 git 仓库，用 `git stash create` 生成一个游离 commit 对象捕获
   已跟踪的脏改动（不动工作区、不动 stash 列表、不动 index），再记录当前 HEAD。
   对非 git 目录，回退到轻量文件拷贝（跳过 node_modules/.venv/.git 等重目录）。
2. **回滚语义**：把**已跟踪文件**恢复到快照时的状态。
   - git：`git reset --hard <head>` + （如有）`git stash apply <stash>` 还原当时的 WIP。
     注意：reset --hard 只动已跟踪文件，agent 新建的未跟踪文件会保留（不误删用户文件）。
   - 文件拷贝：把快照里的文件拷回原位。
3. **默认关闭、按需实例化**：只有显式调用工具的 agent（executor）才会用到；
   其它 agent 与既有测试零影响。

对外只暴露两个工具函数：`checkpoint(path, label)` 与 `rollback(path, checkpoint_id)`，
外加 `list_checkpoints(path)`，以及给 worker 注册用的 `GIT_SAFETY_TOOL_DEFS` /
`build_git_safety_dispatch()`。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional


def _norm(p: str) -> str:
    """规范化路径用于比较：吸收 Windows 上正/反斜杠、大小写、相对差异，
    避免 git --show-toplevel（正斜杠）与 str(Path)（反斜杠）被当成两个目录。"""
    return os.path.normcase(os.path.normpath(p))


def _resolve_bases(path: str) -> list[str]:
    """返回该 path 关联的去重后的快照根目录列表（git 顶层 + 自身目录）。"""
    p = Path(path)
    bases: list[str] = []
    seen: set[str] = set()

    def _add(b: Optional[str]):
        if not b:
            return
        k = _norm(b)
        if k not in seen:
            seen.add(k)
            bases.append(b)

    if _is_git_repo(path):
        _add(_git_toplevel(path))
    _add(str(p if p.is_dir() else p.parent))
    return bases

# 文件拷贝快照时跳过的重目录/模式（避免拷 node_modules 这种大块头）
_COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
    "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".anima_snapshots", "*.pyc", "*.pyo", ".DS_Store",
)

_SNAP_DIRNAME = ".anima_snapshots"


def _run_git(args: list[str], cwd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        timeout=timeout, encoding="utf-8", errors="replace",
    )


def _is_git_repo(path: str) -> bool:
    try:
        r = _run_git(["rev-parse", "--is-inside-work-tree"], path)
        return r.returncode == 0 and r.stdout.strip() == "true"
    except Exception:
        return False


def _git_toplevel(path: str) -> Optional[str]:
    try:
        r = _run_git(["rev-parse", "--show-toplevel"], path)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


# ── 元数据存取（落在仓库/目录下的 .anima_snapshots/index.json）────────────────

def _snap_root(base: str) -> Path:
    return Path(base) / _SNAP_DIRNAME


def _index_path(base: str) -> Path:
    return _snap_root(base) / "index.json"


def _load_index(base: str) -> list[dict]:
    p = _index_path(base)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_index(base: str, items: list[dict]) -> None:
    root = _snap_root(base)
    root.mkdir(parents=True, exist_ok=True)
    _index_path(base).write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _new_id() -> str:
    return f"cp_{int(time.time() * 1000):x}"


# ── 核心：快照 / 回滚 / 列表 ────────────────────────────────────────────────

def checkpoint(path: str, label: str = "") -> dict:
    """对 path 所在项目打一个非破坏性快照，返回 {checkpoint_id, mode, ...}。"""
    p = Path(path)
    if not p.exists():
        return {"error": f"路径不存在: {path}"}

    cp_id = _new_id()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    if _is_git_repo(path):
        base = _git_toplevel(path) or path
        head = _run_git(["rev-parse", "HEAD"], base)
        if head.returncode != 0:
            # 空仓库（还没有任何 commit）——退回文件拷贝
            return _checkpoint_copy(base, cp_id, label, ts, reason="git仓库尚无commit")
        head_sha = head.stdout.strip()
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], base).stdout.strip()
        # 非破坏性捕获已跟踪的脏改动（含 index）；干净则返回空
        stash = _run_git(["stash", "create", f"anima snapshot {cp_id}"], base)
        stash_sha = stash.stdout.strip() or None
        if stash_sha:
            # 让这个游离 stash commit 不被 gc 回收
            _run_git(["update-ref", f"refs/anima/{cp_id}", stash_sha], base)
        rec = {
            "id": cp_id, "mode": "git", "base": base, "label": label,
            "ts": ts, "head": head_sha, "branch": branch, "stash": stash_sha,
        }
        items = _load_index(base)
        items.append(rec)
        _save_index(base, items)
        return {"checkpoint_id": cp_id, "mode": "git", "head": head_sha[:8],
                "dirty_captured": bool(stash_sha), "label": label,
                "note": "已打 git 快照（非破坏性）。回滚用 rollback(path, checkpoint_id)。"}

    # 非 git：文件拷贝
    base = str(p if p.is_dir() else p.parent)
    return _checkpoint_copy(base, cp_id, label, ts)


def _checkpoint_copy(base: str, cp_id: str, label: str, ts: str,
                     reason: str = "") -> dict:
    dest = _snap_root(base) / cp_id
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(base, dest, ignore=_COPY_IGNORE, dirs_exist_ok=True)
    except Exception as e:
        return {"error": f"文件拷贝快照失败: {e}"}
    rec = {"id": cp_id, "mode": "copy", "base": base, "label": label,
           "ts": ts, "snap_dir": str(dest)}
    items = _load_index(base)
    items.append(rec)
    _save_index(base, items)
    out = {"checkpoint_id": cp_id, "mode": "copy", "label": label,
           "note": "已打文件拷贝快照。回滚用 rollback(path, checkpoint_id)。"}
    if reason:
        out["fallback_reason"] = reason
    return out


def _find_record(base: str, checkpoint_id: str) -> Optional[dict]:
    for rec in _load_index(base):
        if rec["id"] == checkpoint_id:
            return rec
    return None


def rollback(path: str, checkpoint_id: str) -> dict:
    """把项目已跟踪文件恢复到指定快照的状态。"""
    p = Path(path)
    if not p.exists():
        return {"error": f"路径不存在: {path}"}

    # 先在 git 顶层找，再在拷贝 base 找
    rec = None
    for b in _resolve_bases(path):
        rec = _find_record(b, checkpoint_id)
        if rec:
            break
    if not rec:
        return {"error": f"未找到快照 {checkpoint_id}"}

    if rec["mode"] == "git":
        return _rollback_git(rec)
    return _rollback_copy(rec)


def _rollback_git(rec: dict) -> dict:
    base = rec["base"]
    head = rec["head"]
    # reset --hard 只动已跟踪文件，不误删 agent 新建的未跟踪文件
    r = _run_git(["reset", "--hard", head], base)
    if r.returncode != 0:
        return {"error": f"git reset 失败: {r.stderr[:300]}"}
    applied_wip = False
    if rec.get("stash"):
        ap = _run_git(["stash", "apply", rec["stash"]], base)
        applied_wip = ap.returncode == 0
    return {"status": "rolled_back", "mode": "git", "head": head[:8],
            "wip_restored": applied_wip,
            "note": "已跟踪文件已恢复到快照状态；agent 新建的未跟踪文件保留未删。"}


def _rollback_copy(rec: dict) -> dict:
    snap_dir = Path(rec["snap_dir"])
    base = Path(rec["base"])
    if not snap_dir.exists():
        return {"error": f"快照目录已丢失: {snap_dir}"}
    restored = 0
    try:
        for src in snap_dir.rglob("*"):
            if src.is_file():
                rel = src.relative_to(snap_dir)
                dst = base / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                restored += 1
    except Exception as e:
        return {"error": f"回滚拷贝失败: {e}"}
    return {"status": "rolled_back", "mode": "copy", "files_restored": restored,
            "note": "快照内文件已拷回；之后新建的文件保留未删。"}


def list_checkpoints(path: str) -> dict:
    """列出该项目已有的快照。"""
    out = []
    for b in _resolve_bases(path):
        for rec in _load_index(b):
            out.append({"checkpoint_id": rec["id"], "mode": rec["mode"],
                        "label": rec.get("label", ""), "ts": rec.get("ts", "")})
    return {"checkpoints": out, "count": len(out)}


# ── worker 注册用 ──────────────────────────────────────────────────────────

GIT_SAFETY_TOOL_DEFS = [
    {"type": "function", "function": {
        "name": "checkpoint",
        "description": "改动多文件前先打一个安全快照（非破坏性）。path=项目根目录，label=备注。返回 checkpoint_id。",
        "parameters": {"type": "object",
            "properties": {
                "path":  {"type": "string", "description": "项目根目录"},
                "label": {"type": "string", "description": "这次快照的备注，比如'重构登录前'"},
            }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "rollback",
        "description": "改崩了就回滚到某个快照（恢复已跟踪文件）。path=项目根目录，checkpoint_id=checkpoint 返回的 id。",
        "parameters": {"type": "object",
            "properties": {
                "path":          {"type": "string"},
                "checkpoint_id": {"type": "string"},
            }, "required": ["path", "checkpoint_id"]},
    }},
    {"type": "function", "function": {
        "name": "list_checkpoints",
        "description": "列出当前项目已打的安全快照。",
        "parameters": {"type": "object",
            "properties": {"path": {"type": "string"}}, "required": ["path"]},
    }},
]


def build_git_safety_dispatch() -> dict:
    return {
        "checkpoint":       lambda **kw: checkpoint(kw["path"], kw.get("label", "")),
        "rollback":         lambda **kw: rollback(kw["path"], kw["checkpoint_id"]),
        "list_checkpoints": lambda **kw: list_checkpoints(kw["path"]),
    }
