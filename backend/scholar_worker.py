#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
守藏 Worker — 知识管理 + Anima 成长管理者
职责：
  1. 普通对话：知识研究、文献分析、深度阅读
  2. SOP 模式：扫描全部聊天记录 → 提炼 → 写入 Obsidian → 更新记忆
  3. Skill 升级：分析低分 Skill，生成改进版，提交升级
"""
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import KIMI_KEY, DATA_DIR, SESSIONS_DB, get_user_address
from persona import compose_base_prompt

# ── Obsidian Vault 路径 ─────────────────────────────────
VAULT_DIR = Path(DATA_DIR).parent.parent / "Anima-Vault"   # ~/Anima-Vault

VAULT_SECTIONS = {
    "daily":    VAULT_DIR / "Daily Notes",
    "people":   VAULT_DIR / "People",
    "projects": VAULT_DIR / "Projects",
    "ideas":    VAULT_DIR / "Ideas",
    "goals":    VAULT_DIR / "Goals",
    "memory":   VAULT_DIR / "Memory",
    "knowledge":VAULT_DIR / "Knowledge",
    "tasks":    VAULT_DIR / "Tasks",
}

def _ensure_vault():
    for p in VAULT_SECTIONS.values():
        p.mkdir(parents=True, exist_ok=True)
    # 创建基础文件
    user_md = VAULT_SECTIONS["memory"] / "USER.md"
    if not user_md.exists():
        user_md.write_text("""# 用户档案
> 由守藏维护，记录用户的偏好、习惯和重要信息

## 基本信息
（待补充）

## 兴趣与偏好
（待观察）

## 近期关注
（待记录）

## 情绪模式
（待观察）

## 重要关系
（待记录）
""", "utf-8")

_ensure_vault()

# ─────────────────────────────────────────────────────────
#  工具定义
# ─────────────────────────────────────────────────────────

FILE_READ_DEF = {
    "type": "function",
    "function": {
        "name": "file_read",
        "description": "读取文件内容（文本文件）",
        "parameters": {
            "type": "object",
            "properties": {
                "path":     {"type": "string", "description": "文件绝对路径"},
                "encoding": {"type": "string", "default": "utf-8"},
            },
            "required": ["path"],
        },
    },
}

READ_CHAT_HISTORY_DEF = {
    "type": "function",
    "function": {
        "name": "read_chat_history",
        "description": "读取所有 Agent 的聊天记录（只读权限）。可按 Agent 和天数筛选。",
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "指定 Agent（xi/yiyi/tianyuan/shoucang/all），默认 all",
                },
                "days": {
                    "type": "integer",
                    "description": "最近 N 天，默认 1（昨天），最大 90",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回多少条会话，默认 50",
                },
            },
            "required": [],
        },
    },
}

WRITE_OBSIDIAN_DEF = {
    "type": "function",
    "function": {
        "name": "write_obsidian_note",
        "description": "在 Obsidian Vault 中写入或更新笔记",
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "保存位置：daily/people/projects/ideas/goals/memory/knowledge/tasks",
                },
                "filename": {
                    "type": "string",
                    "description": "文件名（不含.md），如 '2025-05-25' 或 '张伟' 或 '定价策略'",
                },
                "content":  {"type": "string", "description": "Markdown 内容"},
                "append":   {
                    "type": "boolean",
                    "description": "true=追加到已有文件末尾，false=覆盖（默认false）",
                },
            },
            "required": ["section", "filename", "content"],
        },
    },
}

READ_OBSIDIAN_DEF = {
    "type": "function",
    "function": {
        "name": "read_obsidian_note",
        "description": "读取 Obsidian Vault 中的笔记",
        "parameters": {
            "type": "object",
            "properties": {
                "section":  {"type": "string", "description": "位置：daily/people/projects/..."},
                "filename": {"type": "string", "description": "文件名（不含.md）"},
            },
            "required": ["section", "filename"],
        },
    },
}

LIST_OBSIDIAN_DEF = {
    "type": "function",
    "function": {
        "name": "list_obsidian_notes",
        "description": "列出 Obsidian Vault 某个区域的所有笔记",
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "位置：daily/people/projects/ideas/goals/memory/knowledge/tasks/all",
                },
            },
            "required": ["section"],
        },
    },
}

UPGRADE_SKILL_DEF = {
    "type": "function",
    "function": {
        "name": "upgrade_skill",
        "description": "升级一个 Skill 的 System Prompt（守藏专用，用于改进 Anima 的能力）",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id":   {"type": "string", "description": "Skill ID，如 emotional_support"},
                "new_prompt": {"type": "string", "description": "改进后的完整 System Prompt"},
                "note":       {"type": "string", "description": "本次升级的原因和改动说明"},
                "weak_points":{"type": "array", "items":{"type":"string"},
                               "description": "更新后的已知弱点列表"},
            },
            "required": ["skill_id", "new_prompt", "note"],
        },
    },
}

LIST_SKILLS_DEF = {
    "type": "function",
    "function": {
        "name": "list_skills_for_review",
        "description": "列出所有 Skill 及其评分统计，用于决定哪些需要升级",
        "parameters": {
            "type": "object",
            "properties": {
                "min_usage": {"type": "integer", "description": "最少使用次数（过滤低样本）"},
                "max_score": {"type": "number",  "description": "只列出平均分低于此值的"},
            },
            "required": [],
        },
    },
}

REMEMBER_DEF = {
    "type": "function",
    "function": {
        "name": "remember",
        "description": "把值得长期记住的事实写入记忆库。这是会被注入到各人格 system prompt "
                       "的持久记忆，不依赖 Obsidian——无论用户是否安装 Obsidian 都生效。"
                       "同一 key 再写会更新而非重复。",
        "parameters": {
            "type": "object",
            "properties": {
                "key":   {"type": "string", "description": "记忆要点的简短标题，如 '职业' '常驻城市' '近期情绪'"},
                "value": {"type": "string", "description": "记忆内容正文"},
                "category": {
                    "type": "string",
                    "description": "分类：user_profile(用户画像) / preference(偏好) / emotional(情感) / "
                                   "business(创业) / knowledge(知识背景) / writing_style(写作风格) / "
                                   "project(项目) / note(笔记) / general(其他)",
                },
                "agent_id": {
                    "type": "string",
                    "description": "这条记忆服务于哪个人格（xi/yiyi/tianyuan/shoucang）。"
                                   "留空=全局，所有人格都可见（用户画像类建议留空）。",
                },
                "importance": {"type": "integer", "description": "重要度 1-5，默认 3"},
            },
            "required": ["key", "value"],
        },
    },
}

LIST_MEMORY_DEF = {
    "type": "function",
    "function": {
        "name": "list_memory",
        "description": "列出记忆库中已有的记忆条目（避免重复写入、便于更新用户画像）。",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "只看某人格相关记忆，留空=全部"},
            },
            "required": [],
        },
    },
}

# ─────────────────────────────────────────────────────────
#  工具实现
# ─────────────────────────────────────────────────────────

def _file_read(path: str, encoding: str = "utf-8") -> dict:
    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"文件不存在: {path}"}
        if p.stat().st_size > 2 * 1024 * 1024:
            return {"error": "文件过大（>2MB），请分段阅读"}
        return {"path": str(p), "content": p.read_text(encoding, errors="replace")[:12000]}
    except Exception as e:
        return {"error": str(e)}


def _read_chat_history(agent: str = "all", days: int = 1, limit: int = 50) -> dict:
    """读取聊天记录（守藏只读权限）"""
    if not SESSIONS_DB.exists():
        return {"sessions": [], "note": "暂无历史记录"}
    try:
        days  = min(max(1, days), 90)
        limit = min(max(1, limit), 200)
        since = (datetime.now() - timedelta(days=days)).timestamp()

        conn = sqlite3.connect(str(SESSIONS_DB))
        conn.row_factory = sqlite3.Row

        if agent and agent != "all":
            cur = conn.execute(
                "SELECT * FROM sessions WHERE agent=? AND timestamp>=? ORDER BY timestamp DESC LIMIT ?",
                (agent, since, limit)
            )
        else:
            cur = conn.execute(
                "SELECT * FROM sessions WHERE timestamp>=? ORDER BY timestamp DESC LIMIT ?",
                (since, limit)
            )
        sessions = [dict(r) for r in cur.fetchall()]

        # 为每个会话附上消息摘要
        for s in sessions:
            try:
                mcur = conn.execute(
                    "SELECT role, content FROM messages WHERE session_id=? ORDER BY id LIMIT 10",
                    (s["session_id"],)
                )
                s["messages"] = [dict(m) for m in mcur.fetchall()]
            except Exception:
                s["messages"] = []

        conn.close()
        return {
            "sessions": sessions,
            "total":    len(sessions),
            "days":     days,
            "agent":    agent,
        }
    except Exception as e:
        return {"error": str(e)}


def _write_obsidian_note(section: str, filename: str, content: str, append: bool = False) -> dict:
    """写入 Obsidian 笔记"""
    _ensure_vault()
    sec_path = VAULT_SECTIONS.get(section)
    if not sec_path:
        return {"error": f"未知 section: {section}，可用: {list(VAULT_SECTIONS.keys())}"}
    path = sec_path / f"{filename}.md"
    try:
        if append and path.exists():
            existing = path.read_text("utf-8")
            path.write_text(existing + "\n\n" + content, "utf-8")
        else:
            path.write_text(content, "utf-8")
        return {
            "ok":      True,
            "path":    str(path),
            "section": section,
            "filename":filename,
            "size":    path.stat().st_size,
        }
    except Exception as e:
        return {"error": str(e)}


def _read_obsidian_note(section: str, filename: str) -> dict:
    sec_path = VAULT_SECTIONS.get(section)
    if not sec_path:
        return {"error": f"未知 section: {section}"}
    path = sec_path / f"{filename}.md"
    if not path.exists():
        return {"error": f"笔记不存在: {section}/{filename}.md"}
    return {
        "content":  path.read_text("utf-8", errors="replace")[:8000],
        "path":     str(path),
        "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
    }


def _list_obsidian_notes(section: str = "all") -> dict:
    _ensure_vault()
    if section == "all":
        result = {}
        for name, path in VAULT_SECTIONS.items():
            files = sorted(path.glob("*.md"))
            result[name] = [f.stem for f in files]
        return result
    sec_path = VAULT_SECTIONS.get(section)
    if not sec_path:
        return {"error": f"未知 section: {section}"}
    files = sorted(sec_path.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
    return {
        "section": section,
        "notes":   [{"name": f.stem, "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
                    for f in files],
        "total":   len(files),
    }


def _upgrade_skill(skill_id: str, new_prompt: str, note: str, weak_points: list = None) -> dict:
    from skill_manager import upgrade_skill
    return upgrade_skill(skill_id, new_prompt, note, weak_points)


def _list_skills_for_review(min_usage: int = 5, max_score: float = 4.0) -> dict:
    from skill_manager import list_skills
    skills = list_skills()
    candidates = [
        {
            "id":          s.get("id"),
            "name":        s.get("name"),
            "avg_score":   s.get("avg_score", 0),
            "usage_count": s.get("usage_count", 0),
            "version":     s.get("version", 1),
            "last_improved": s.get("last_improved", ""),
            "weak_points": s.get("weak_points", []),
        }
        for s in skills
        if s.get("usage_count", 0) >= min_usage and s.get("avg_score", 5) <= max_score
    ]
    return {
        "candidates":     candidates,
        "total_reviewed": len(skills),
        "needs_upgrade":  len(candidates),
    }


_VALID_CATEGORIES = {
    "user_profile", "preference", "emotional", "business",
    "knowledge", "writing_style", "project", "note", "general",
}


def _remember(key: str, value: str, category: str = "general",
              agent_id: str = None, importance: int = 3) -> dict:
    """把事实写入激活的记忆后端（默认 SQLite，无需 Obsidian），下次对话即注入。"""
    if not key or not value:
        return {"error": "key / value 不能为空"}
    if category not in _VALID_CATEGORIES:
        category = "general"
    agent_id = (agent_id or "").strip() or None   # 空串=全局
    try:
        importance = max(1, min(5, int(importance)))
    except Exception:
        importance = 3
    try:
        from memory_injector import write_memory
        eid = write_memory(key=key, value=value, category=category,
                           agent_id=agent_id, importance=importance)
        return {"ok": True, "id": eid, "key": key,
                "category": category, "agent_id": agent_id}
    except Exception as e:
        return {"error": str(e)}


def _list_memory(agent_id: str = None) -> dict:
    """列出记忆库已有条目（便于去重 / 更新用户画像）。"""
    agent_id = (agent_id or "").strip() or None
    try:
        from memory_injector import list_memory
        entries = list_memory(agent_id)
        return {"total": len(entries),
                "entries": [{"id": e.id, "key": e.key, "value": e.value,
                             "category": e.category, "agent_id": e.agent_id,
                             "importance": e.importance} for e in entries]}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────
#  ShoucangWorker
# ─────────────────────────────────────────────────────────

class ShoucangWorker(AgentBase):
    def __init__(self):
        from websearch import WEB_SEARCH_TOOL_DEFS, build_dispatch
        tool_defs = [
            FILE_READ_DEF,
            READ_CHAT_HISTORY_DEF,
            WRITE_OBSIDIAN_DEF,
            READ_OBSIDIAN_DEF,
            LIST_OBSIDIAN_DEF,
            UPGRADE_SKILL_DEF,
            LIST_SKILLS_DEF,
            REMEMBER_DEF,            # 写入可注入记忆库（不依赖 Obsidian）
            LIST_MEMORY_DEF,
            *WEB_SEARCH_TOOL_DEFS,   # 文献研究需要联网检索（共享 websearch 能力）
        ]
        tool_dispatch = {
            "file_read":            _file_read,
            "read_chat_history":    _read_chat_history,
            "write_obsidian_note":  _write_obsidian_note,
            "read_obsidian_note":   _read_obsidian_note,
            "list_obsidian_notes":  _list_obsidian_notes,
            "upgrade_skill":        _upgrade_skill,
            "list_skills_for_review": _list_skills_for_review,
            "remember":             lambda **kw: _remember(
                                        kw["key"], kw["value"], kw.get("category", "general"),
                                        kw.get("agent_id"), kw.get("importance", 3)),
            "list_memory":          lambda **kw: _list_memory(kw.get("agent_id")),
            **build_dispatch(),
        }
        super().__init__(
            name="shoucang",
            api_key=KIMI_KEY,
            model="kimi-k2.6",
            base_url="https://api.moonshot.cn/v1",
            system_prompt=compose_base_prompt("shoucang"),
            tool_defs=tool_defs,
            tool_dispatch=tool_dispatch,
        )
        self.max_turns = 40

    def run_daily_sop(self, progress_cb=None) -> dict:
        """
        每日 SOP：扫描昨日对话 → 提炼 → 写入 Obsidian → 更新记忆 → 检查 Skill
        由定时任务每晚 23:00 调用，也可由用户手动触发。

        progress_cb: 可选回调 fn(step: int, total: int, msg: str)，用于前端进度推送
        """
        import asyncio

        def _cb(step, total, msg):
            if progress_cb:
                try:
                    progress_cb(step, total, msg)
                except Exception:
                    pass

        _cb(0, 6, "开始 SOP...")

        today = date.today().isoformat()

        # 分阶段执行，每阶段推送进度
        stages = [
            ("读取聊天记录", "read_chat_history"),
            ("提炼关键信息", "extract"),
            ("写入 Obsidian", "write_notes"),
            ("更新用户记忆", "update_user"),
            ("检查 Skill 升级", "skill_review"),
            ("清理缓存", "cleanup"),
        ]

        prompt = f"""请分步骤执行今日知识整理 SOP（{today}），每完成一步就继续下一步：

步骤1：read_chat_history(agent="all", days=1, limit=100)
步骤2：提炼关键信息（人名/项目/任务/决策/知识点/情绪状态/用户喜好变化）
步骤3【长期记忆，最重要】：把值得长期记住的事实写进记忆库——这是会被注入到各人格对话里的记忆，
       不依赖 Obsidian，所有用户都生效。先 list_memory() 看已有的，避免重复；再用 remember() 写入/更新：
       - 用户画像、稳定事实（职业/城市/家庭等）→ remember(category="user_profile", agent_id=null)  ← 留空=全局，所有人格可见
       - 偏好/习惯 → remember(category="preference", agent_id=null)
       - 情绪状态、心结、在意的人 → remember(category="emotional", agent_id="yiyi")  ← 给晞
       - 创业/业务进展 → remember(category="business", agent_id="tianyuan")  ← 给陶朱
       - 知识背景 → remember(category="knowledge", agent_id=null)
       同一件事用同一个 key，再写即更新，不要堆重复条目。
步骤4【人类可读日志，本地 Markdown】：写 Obsidian 笔记（即使没装 Obsidian 也只是本地 .md 文件，可正常生成）：
       write_obsidian_note(section="daily", filename="{today}", content=<今日日记>)
       如有新人物 → write_obsidian_note(section="people", filename=<人名>, content=<信息>)
       如有项目进展 → write_obsidian_note(section="projects", filename=<项目名>, content=<进展>, append=True)
       如有值得保存的知识 → write_obsidian_note(section="knowledge", filename=<主题>, content=<内容>)
步骤5：list_skills_for_review() → 对平均分<3.5的Skill进行分析 → upgrade_skill()
步骤6：输出本次 SOP 执行摘要（一段话，包含：写入了哪些长期记忆、今日日记、Skill升级情况）

注意：长期记忆以步骤3的 remember() 为准（保证无 Obsidian 也能闭环）；Obsidian 笔记是给人看的本地日志，二者都要做。
请开始，逐步执行。"""

        _cb(1, 6, "守藏开始读取对话记录...")

        # 用 asyncio 在当前线程运行异步 run()
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.run(prompt))
        finally:
            loop.close()

        _cb(6, 6, "SOP 完成")

        # SOP 完成后使记忆缓存失效（让下次对话读取最新记忆）
        try:
            from memory_injector import invalidate_cache
            invalidate_cache()
        except Exception:
            pass

        return result


# ─────────────────────────────────────────────────────────
#  Obsidian HTTP API 辅助函数（供 websocket_server 调用）
# ─────────────────────────────────────────────────────────

def get_vault_tree() -> dict:
    """返回 Vault 文件树（给前端渲染）"""
    _ensure_vault()
    tree = {}
    for section, path in VAULT_SECTIONS.items():
        files = sorted(path.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
        tree[section] = [
            {
                "name":     f.stem,
                "path":     str(f),
                "size":     f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            }
            for f in files
        ]
    return tree


def read_vault_file(path_str: str) -> dict:
    """读取 Vault 文件（给前端编辑器）"""
    p = Path(path_str)
    if not p.exists() or not str(p).startswith(str(VAULT_DIR)):
        return {"error": "文件不存在或路径不在 Vault 内"}
    return {
        "content":  p.read_text("utf-8", errors="replace"),
        "path":     str(p),
        "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
    }


def write_vault_file(path_str: str, content: str) -> dict:
    """写入 Vault 文件（前端编辑器保存）"""
    p = Path(path_str)
    if not str(p).startswith(str(VAULT_DIR)):
        return {"error": "路径必须在 Vault 目录内"}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, "utf-8")
    return {"ok": True, "path": str(p)}


def get_vault_dir() -> str:
    return str(VAULT_DIR)
