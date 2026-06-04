#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anima Worker — 私人助理（核心 Agent）
继承 AgentBase，带完整编程工具集
"""
import sys, subprocess, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase, PermissionRequest
from config import DEEPSEEK_KEY, WORKSPACE_DIR, get_user_address
from persona import compose_base_prompt

# ── 工具实现 ──────────────────────────────────────────────────────────────────

def _list_dir(path: str, max_depth: int = 2) -> dict:
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
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        sliced = lines[offset:offset + limit]
        return {"path": path, "content": "\n".join(sliced),
                "total_lines": len(lines), "offset": offset, "shown": len(sliced)}
    except Exception as e:
        return {"error": str(e)}

def _write_file(path: str, content: str) -> dict:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"path": path, "bytes": len(content.encode())}
    except Exception as e:
        return {"error": str(e)}

def _edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
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
        return {"path": path, "replaced": count}
    except Exception as e:
        return {"error": str(e)}

def _search_code(pattern: str, path: str = ".", file_glob: str = "*", limit: int = 30) -> dict:
    try:
        import re
        results = []
        for fpath in Path(path).rglob(file_glob):
            if not fpath.is_file() or fpath.stat().st_size > 2_000_000:
                continue
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

_FORBIDDEN = {"rm -rf /", "format", "del /f /s /q c:\\", "shutdown", "mkfs", ":(){:|:&};:"}

def _shell_run(command: str, timeout: int = 60, cwd: str | None = None) -> dict:
    low = command.lower()
    if any(bad in low for bad in _FORBIDDEN):
        return {"error": f"命令被安全策略拒绝: {command[:80]}"}
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd or str(WORKSPACE_DIR),
            encoding="utf-8", errors="replace",
        )
        return {
            "exit_code": result.returncode,
            "stdout":    result.stdout[:3000],
            "stderr":    result.stderr[:1000],
        }
    except subprocess.TimeoutExpired:
        return {"error": f"命令超时（{timeout}s）", "exit_code": -1}
    except Exception as e:
        return {"error": str(e), "exit_code": -1}


# 联网检索已抽到共享模块 websearch.py（统一配额 + 缓存）。
# 这里保留同名别名，兼容历史 `from xi_worker import _web_search, _fetch_url`。
from websearch import web_search as _web_search, fetch_url as _fetch_url  # noqa: E402


class XiWorker(AgentBase):
    """Anima（整合版"她"）——由 profile 声明的能力积木组装而成。

    能力（capabilities.py）：
      execution   动手做事（文件/命令/代码）
      web         联网检索
      divination  命理排盘（八字 + 紫微）
      orchestration 调动子员工拆大活
    记忆由 AgentBase 自动注入，不在此列。
    """
    CAPS = ["execution", "web", "divination", "orchestration"]

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

    async def run(self, task, session_id=None, model=None, ws=None, project=None):
        # 记录用户消息到语言图谱（容错，不阻塞主流程）
        try:
            import lang_profile as _lp
            _lp.record_message(str(task))
        except Exception:
            pass
        # 每次对话前刷新 system prompt（含最新出生信息和语言图谱）
        self.system_prompt = self._compose_system()
        return await super().run(task, session_id=session_id, model=model,
                                 ws=ws, project=project)
