#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
git_tools.py — v1.2.1 T7：Git 工作流六件套（原生工具）

区别于 git_safety.py（checkpoint/rollback 非破坏性快照）：本模块是面向 Agent 的
**常规 git 操作**——查变更、看 diff、本地提交、看历史、管分支。

安全约束（plan §七）：
  · 全部用 subprocess 列表参数（shell=False），message/branch 不经 shell，杜绝注入。
  · git_commit：空 message 拒绝；**绝不 push**；暂存的敏感文件（.env/.ssh/密钥）
    自动排除，不混进提交。
  · 不可逆的 push/发布留给用户手动执行（N5 定位）。

对外：6 个 `_git_*` 函数 + `GIT_TOOL_DEFS` + `build_git_dispatch()`。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# 暂存区里绝不允许被提交的敏感文件（按路径分段/后缀匹配）
_SENSITIVE_RE = re.compile(
    r"(^|/)\.env($|\.|/)|(^|/)\.ssh/|id_rsa|id_ed25519|id_dsa|"
    r"\.pem$|\.key$|(^|/)credentials($|\.|/)|(^|/)secrets?($|\.|/)",
    re.IGNORECASE,
)
_BRANCH_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._/\-]*[A-Za-z0-9_\-])?$")
_DIFF_CAP = 12000
_LOG_CAP = 100


def _run_git(args: list[str], cwd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _ensure_repo(path: str):
    """校验 path 是已有目录且在 git 工作树内。返回错误 dict 或 None。"""
    p = Path(path)
    if not p.exists():
        return {"error": f"路径不存在: {path}"}
    if not p.is_dir():
        path = str(p.parent)
    try:
        r = _run_git(["rev-parse", "--is-inside-work-tree"], path)
    except FileNotFoundError:
        return {"error": "未找到 git 可执行文件，请先安装 git"}
    except Exception as e:
        return {"error": str(e)}
    if r.returncode != 0 or "true" not in r.stdout.lower():
        return {"error": f"不是 git 仓库: {path}"}
    return None


def _git_status(path: str = ".") -> dict:
    err = _ensure_repo(path)
    if err:
        return err
    try:
        br = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], path)
        st = _run_git(["status", "--porcelain"], path)
        changes = []
        for line in st.stdout.splitlines():
            if line.strip():
                changes.append({"status": line[:2].strip(), "file": line[3:]})
        return {"branch": br.stdout.strip(), "changes": changes,
                "clean": len(changes) == 0}
    except Exception as e:
        return {"error": str(e)}


def _git_diff(path: str = ".", staged: bool = False, file: str | None = None) -> dict:
    err = _ensure_repo(path)
    if err:
        return err
    try:
        args = ["diff"]
        if staged:
            args.append("--staged")
        if file:
            args += ["--", file]
        r = _run_git(args, path)
        out = r.stdout
        return {"diff": out[:_DIFF_CAP], "truncated": len(out) > _DIFF_CAP,
                "staged": staged}
    except Exception as e:
        return {"error": str(e)}


def _git_commit(path: str = ".", message: str = "") -> dict:
    err = _ensure_repo(path)
    if err:
        return err
    if not message or not message.strip():
        return {"error": "提交信息不能为空"}
    try:
        _run_git(["add", "-A"], path)
        # 敏感文件守卫：把暂存区里的 .env/.ssh/密钥类文件撤出暂存，绝不提交
        staged = _run_git(["diff", "--cached", "--name-only"], path)
        excluded = [f for f in staged.stdout.splitlines()
                    if f.strip() and _SENSITIVE_RE.search(f)]
        for f in excluded:
            _run_git(["reset", "-q", "HEAD", "--", f], path)
        remaining = _run_git(["diff", "--cached", "--name-only"], path)
        if not remaining.stdout.strip():
            msg = "没有可提交的变更"
            if excluded:
                msg += "（仅有敏感文件，已被安全策略排除）"
            return {"committed": False, "reason": msg, "excluded_sensitive": excluded}
        c = _run_git(["commit", "-m", message], path)
        if c.returncode != 0:
            return {"committed": False, "error": (c.stderr or c.stdout).strip()[:500],
                    "excluded_sensitive": excluded}
        h = _run_git(["rev-parse", "--short", "HEAD"], path)
        return {"committed": True, "hash": h.stdout.strip(),
                "message": message, "excluded_sensitive": excluded}
    except Exception as e:
        return {"error": str(e)}


def _git_log(path: str = ".", limit: int = 10) -> dict:
    err = _ensure_repo(path)
    if err:
        return err
    try:
        limit = max(1, min(int(limit), _LOG_CAP))
    except Exception:
        limit = 10
    try:
        r = _run_git(["log", f"-{limit}", "--pretty=format:%h %s"], path)
        commits = [ln for ln in r.stdout.splitlines() if ln.strip()]
        return {"commits": commits, "count": len(commits)}
    except Exception as e:
        return {"error": str(e)}


def _git_branch(path: str = ".") -> dict:
    err = _ensure_repo(path)
    if err:
        return err
    try:
        cur = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], path)
        lst = _run_git(["branch", "--format=%(refname:short)"], path)
        branches = [b.strip() for b in lst.stdout.splitlines() if b.strip()]
        return {"current": cur.stdout.strip(), "branches": branches}
    except Exception as e:
        return {"error": str(e)}


def _git_create_branch(path: str = ".", name: str = "") -> dict:
    err = _ensure_repo(path)
    if err:
        return err
    name = (name or "").strip()
    if not _BRANCH_RE.match(name):
        return {"error": f"非法分支名: {name!r}（仅允许字母数字和 ._/-）"}
    try:
        r = _run_git(["checkout", "-b", name], path)
        if r.returncode != 0:
            return {"created": False, "error": (r.stderr or r.stdout).strip()[:300]}
        return {"created": True, "branch": name}
    except Exception as e:
        return {"error": str(e)}


# ── 工具定义 + dispatch（供 capabilities._execution_cap 与 executor 共享）─────────

GIT_TOOL_DEFS = [
    {"type": "function", "function": {
        "name": "git_status", "description": "查看 git 仓库变更（当前分支 + 改动文件列表）",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "仓库路径，默认当前目录"},
        }, "required": []}}},
    {"type": "function", "function": {
        "name": "git_diff", "description": "查看改动 diff（可选只看暂存区或单个文件）",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "staged": {"type": "boolean", "description": "只看已暂存的改动"},
            "file": {"type": "string", "description": "只看某个文件的 diff"},
        }, "required": []}}},
    {"type": "function", "function": {
        "name": "git_commit",
        "description": "本地提交（git add -A 后 commit）。空信息拒绝；绝不 push；"
                       "暂存的 .env/.ssh/密钥类敏感文件会被自动排除。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "message": {"type": "string", "description": "提交信息（必填）"},
        }, "required": ["message"]}}},
    {"type": "function", "function": {
        "name": "git_log", "description": "查看最近的提交历史（简短格式）",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "limit": {"type": "integer", "description": "返回条数，默认 10，上限 100"},
        }, "required": []}}},
    {"type": "function", "function": {
        "name": "git_branch", "description": "查看当前分支与本地分支列表",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
        }, "required": []}}},
    {"type": "function", "function": {
        "name": "git_create_branch", "description": "新建并切换到一个分支",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "name": {"type": "string", "description": "新分支名（字母数字 ._/-）"},
        }, "required": ["name"]}}},
]


def build_git_dispatch() -> dict:
    return {
        "git_status":        lambda **kw: _git_status(kw.get("path", ".")),
        "git_diff":          lambda **kw: _git_diff(kw.get("path", "."), kw.get("staged", False), kw.get("file")),
        "git_commit":        lambda **kw: _git_commit(kw.get("path", "."), kw.get("message", "")),
        "git_log":           lambda **kw: _git_log(kw.get("path", "."), kw.get("limit", 10)),
        "git_branch":        lambda **kw: _git_branch(kw.get("path", ".")),
        "git_create_branch": lambda **kw: _git_create_branch(kw.get("path", "."), kw.get("name", "")),
    }
