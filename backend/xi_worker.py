#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anima Worker — 私人助理（核心 Agent）
继承 AgentBase，带完整编程工具集
"""
import difflib
import sys, subprocess, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase, PermissionRequest
from config import DEEPSEEK_KEY, WORKSPACE_DIR, get_user_address
from persona import compose_base_prompt

# ── 工具实现 ──────────────────────────────────────────────────────────────────

_DIFF_MAX_LINES = 200

def _make_diff(old: str, new: str, path: str) -> str:
    """D4: 生成截断到 200 行的 unified diff，供 tool_done WS 事件推送。"""
    lines = list(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{Path(path).name}", tofile=f"b/{Path(path).name}",
    ))
    if len(lines) > _DIFF_MAX_LINES:
        lines = lines[:_DIFF_MAX_LINES]
        lines.append(f"\n... 截断（共 {len(lines)} 行）\n")
    return "".join(lines)

def _sandbox(path: str, write: bool = False):
    """文件访问护栏：拦截凭证/系统路径。返回拒绝原因 dict，放行返回 None。"""
    try:
        import path_sandbox
        ok, reason = path_sandbox.check_path(path, write=write)
        if not ok:
            return {"error": reason}
    except Exception:
        # 护栏模块异常时不阻断正常使用（fail-open），但拒绝判定本身 fail-closed
        pass
    return None

def _list_dir(path: str, max_depth: int = 2) -> dict:
    _blk = _sandbox(path, write=False)
    if _blk:
        return _blk
    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"路径不存在: {path}"}
        items = []
        for item in p.rglob("*"):
            depth = len(item.relative_to(p).parts)
            if depth > max_depth:
                continue
            items.append({
                "path": str(item),
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
        return {"path": path, "items": items[:200]}
    except Exception as e:
        return {"error": str(e)}

def _read_file(path: str, offset: int = 0, limit: int = 200) -> dict:
    _blk = _sandbox(path, write=False)
    if _blk:
        return _blk
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        sliced = lines[offset:offset + limit]
        return {"path": path, "content": "\n".join(sliced),
                "total_lines": len(lines), "offset": offset, "shown": len(sliced)}
    except Exception as e:
        return {"error": str(e)}

def _write_file(path: str, content: str) -> dict:
    _blk = _sandbox(path, write=True)
    if _blk:
        return _blk
    try:
        p = Path(path)
        old = p.read_text(encoding="utf-8") if p.exists() else ""
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"path": path, "bytes": len(content.encode()),
                "diff": _make_diff(old, content, path)}
    except Exception as e:
        return {"error": str(e)}

def _edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
    _blk = _sandbox(path, write=True)
    if _blk:
        return _blk
    try:
        p = Path(path)
        content = p.read_text(encoding="utf-8")
        if old_string not in content:
            return {"error": f"未找到目标字符串（前30字符）: {old_string[:30]!r}"}
        if replace_all:
            new_content = content.replace(old_string, new_string)
            count = content.count(old_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            count = 1
        p.write_text(new_content, encoding="utf-8")
        return {"path": path, "replaced": count,
                "diff": _make_diff(content, new_content, path)}
    except Exception as e:
        return {"error": str(e)}

def _search_code(pattern: str, path: str = ".", file_glob: str = "*", limit: int = 30) -> dict:
    _blk = _sandbox(path, write=False)
    if _blk:
        return _blk
    try:
        import re
        import path_sandbox
        results = []
        for fpath in Path(path).rglob(file_glob):
            if not fpath.is_file() or fpath.stat().st_size > 2_000_000:
                continue
            # 跳过命中护栏的敏感文件（如目录下混有 id_rsa、.ssh 等）
            try:
                _ok, _ = path_sandbox.check_path(str(fpath), write=False)
                if not _ok:
                    continue
            except Exception:
                pass
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if re.search(pattern, line):
                        results.append({"file": str(fpath), "line": i, "content": line.strip()})
                        if len(results) >= limit:
                            return {"results": results, "truncated": True}
            except Exception:
                pass
        return {"results": results, "truncated": False}
    except Exception as e:
        return {"error": str(e)}


def _glob_files(pattern: str, path: str = ".", limit: int = 100) -> dict:
    """按文件名 glob 模式查找文件（支持 ** 递归，如 '**/*.test.py'）。
    区别于 search_code（搜内容）——这里只按文件名匹配，结果按修改时间降序，
    最近改动的在前，符合「找最相关文件」的直觉。命中护栏的敏感文件自动跳过。"""
    _blk = _sandbox(path, write=False)
    if _blk:
        return _blk
    try:
        import path_sandbox
        base = Path(path)
        if not base.exists():
            return {"error": f"路径不存在: {path}"}
        matches = []
        for fpath in base.glob(pattern):
            if not fpath.is_file():
                continue
            try:
                _ok, _ = path_sandbox.check_path(str(fpath), write=False)
                if not _ok:
                    continue
            except Exception:
                pass
            matches.append(fpath)
            if len(matches) >= 2000:   # 安全上限，避免巨型目录撑爆
                break
        matches.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        files = [str(f) for f in matches[:limit]]
        return {"pattern": pattern, "path": path, "files": files,
                "count": len(files), "truncated": len(matches) > limit}
    except Exception as e:
        return {"error": str(e)}


# 项目全景树跳过的噪声目录（依赖/缓存/构建产物/IDE）
_MAP_IGNORE = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", ".cache", "target", ".idea",
    ".vscode", "coverage", ".pytest_cache", ".mypy_cache", "site-packages",
    ".gradle", "vendor", ".turbo", ".parcel-cache",
}

def _map_project(root: str = ".", max_depth: int = 3) -> dict:
    """项目全景目录树：渲染缩进树（自动跳过 node_modules/.git 等噪声），
    供 Agent 开工第一步快速建立项目结构认知，省下前几轮的逐目录探索。"""
    _blk = _sandbox(root, write=False)
    if _blk:
        return _blk
    try:
        base = Path(root)
        if not base.exists():
            return {"error": f"路径不存在: {root}"}
        lines: list[str] = []
        counts = {"dirs": 0, "files": 0}
        MAX_ENTRIES = 400

        def walk(d: Path, depth: int):
            if depth > max_depth or len(lines) >= MAX_ENTRIES:
                return
            try:
                entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except Exception:
                return
            for item in entries:
                if len(lines) >= MAX_ENTRIES:
                    return
                if item.is_dir():
                    if item.name in _MAP_IGNORE:
                        continue
                    counts["dirs"] += 1
                    lines.append("  " * depth + item.name + "/")
                    walk(item, depth + 1)
                else:
                    counts["files"] += 1
                    lines.append("  " * depth + item.name)

        walk(base, 0)
        truncated = len(lines) >= MAX_ENTRIES
        return {"root": str(base), "tree": "\n".join(lines),
                "dirs": counts["dirs"], "files": counts["files"],
                "truncated": truncated}
    except Exception as e:
        return {"error": str(e)}


import re as _re

# 精确危险命令检测（替换旧的裸子串匹配，避免误杀 npm run format / git log --format 等正常命令）
def _is_dangerous(cmd: str) -> bool:
    low = cmd.strip().lower()
    # Windows 磁盘格式化：format c: / format d: / format /dev/...
    if _re.search(r'\bformat\s+[a-z]:', low) or _re.search(r'\bformat\s+/dev/', low):
        return True
    # Unix 根目录递归删除
    if _re.search(r'rm\s+.*-[^\s]*r.*\s+/', low) or "rm -rf /" in low:
        return True
    # Windows 强制删除系统盘
    if "del /f /s /q c:\\" in low or "del /f /s /q c:/" in low:
        return True
    # 关机/格盘/fork炸弹
    if _re.search(r'\bshutdown\b', low) or _re.search(r'\bmkfs\b', low):
        return True
    if ":(){:|:&};:" in cmd:
        return True
    return False


def _shell_run(command: str, timeout: int = 60, cwd: str | None = None) -> dict:
    if _is_dangerous(command):
        return {"error": f"命令被安全策略拒绝: {command[:80]}"}
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd or str(WORKSPACE_DIR),
            encoding="utf-8", errors="replace",
        )
        return {
            "exit_code": result.returncode,
            "stdout":    result.stdout[:8000],
            "stderr":    result.stderr[:2000],
        }
    except subprocess.TimeoutExpired:
        return {"error": f"命令超时（{timeout}s）", "exit_code": -1}
    except Exception as e:
        return {"error": str(e), "exit_code": -1}


# 联网检索已抽到共享模块 websearch.py（统一配额 + 缓存）。
# 这里保留同名别名，兼容历史 `from xi_worker import _web_search, _fetch_url`。
# ── N2: update_plan（计划可见性工具）──────────────────────────────────────────

_session_plans: dict[str, list] = {}

def _update_plan(steps: list, session_id: str = "") -> dict:
    """Agent 维护自己的执行计划。每个 step: {text, status: pending/doing/done}
    调用即覆盖整个计划（全量重报），通过 WS 推送给前端渲染清单卡片。"""
    if not steps or not isinstance(steps, list):
        return {"error": "steps 必须是非空列表"}
    normalized = []
    for s in steps:
        if isinstance(s, str):
            normalized.append({"text": s, "status": "pending"})
        elif isinstance(s, dict):
            normalized.append({
                "text": str(s.get("text", "")),
                "status": s.get("status", "pending"),
            })
    _session_plans[session_id] = normalized
    return {"ok": True, "steps": normalized, "count": len(normalized)}


from websearch import web_search as _web_search, fetch_url as _fetch_url  # noqa: E402


class XiWorker(AgentBase):
    """Anima（整合版"她"）——由 profile 声明的能力积木组装而成。

    能力（capabilities.py）：
      execution   动手做事（文件/命令/代码）
      web         联网检索
      divination  命理排盘（八字 + 紫微）
      orchestration 调动子员工拆大活
      memory      记忆积木（remember/recall/forget，写入分级见 §3.1）
    记忆注入仍由 AgentBase 自动处理；此处的 memory 只是写入/检索工具。
    """
    CAPS = ["execution", "web", "divination", "orchestration", "memory", "mcp"]

    def __init__(self):
        from capabilities import build as _build_caps
        comp = _build_caps(self.CAPS, agent_id="xi")
        # 能力贡献的提示词片段（静态）与动态钩子（每次 run 取最新，如出生信息）
        self._cap_fragments = comp["fragments"]
        self._cap_dynamic = comp["dynamic"]

        super().__init__(
            name="xi",
            api_key=DEEPSEEK_KEY,
            model="deepseek-v4-pro",   # 整合版要写代码+派活+情感，用最强档
            base_url="https://api.deepseek.com",
            system_prompt=compose_base_prompt("xi"),  # 基底；run 前由 _compose_system 刷新
            tool_defs=comp["tool_defs"],
            tool_dispatch=comp["dispatch"],
        )
        # 聊天人格：回复去 AI 味（清洗 Markdown 装饰符号），温度略高更自然
        self.humanize_output = True
        self.temperature = 0.75
        self.max_turns = 30

    def _compose_system(self) -> str:
        """人格底色 + 各能力的动态片段（出生信息等）+ 静态用法片段 + 语言图谱。"""
        parts = [compose_base_prompt("xi")]
        for hook in self._cap_dynamic:
            try:
                t = hook()
                if t:
                    parts.append(t)
            except Exception:
                pass
        parts.extend(self._cap_fragments)
        # 语言图谱：积累 UPDATE_EVERY 条后才注入，数据不足时静默跳过
        try:
            import lang_profile as _lp
            lp = _lp.get_profile_block()
            if lp:
                parts.append(lp)
        except Exception:
            pass
        return "\n".join(p for p in parts if p)

    def _sync_mcp_tools(self):
        """热加载：把当前已连接的 MCP 工具并进 tool_defs/dispatch。
        靠 mcp__ 前缀只换 MCP 子集，原生 13 工具一字不动。
        用户运行中加完 server，下一句话即可用，无需重启。容错：任何异常静默跳过。"""
        try:
            from mcp_client import MCPManager
            snap = MCPManager.snapshot()
            base_defs = [d for d in self.tool_defs
                         if not d["function"]["name"].startswith("mcp__")]
            self.tool_defs = base_defs + snap.tool_defs
            self.tool_dispatch = {k: v for k, v in self.tool_dispatch.items()
                                  if not k.startswith("mcp__")}
            self.tool_dispatch.update(snap.dispatch)
        except Exception:
            pass

    async def run(self, task, session_id=None, model=None, ws=None, project=None):
        # 记录用户消息到语言图谱（容错，不阻塞主流程）
        try:
            import lang_profile as _lp
            _lp.record_message(str(task))
        except Exception:
            pass
        # 热加载 MCP 工具（boot 可能晚于构造 / 运行中新增 server）
        self._sync_mcp_tools()
        # 每次对话前刷新 system prompt（含最新出生信息和语言图谱）
        self.system_prompt = self._compose_system()
        return await super().run(task, session_id=session_id, model=model,
                                 ws=ws, project=project)
