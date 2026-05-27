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

SHOUCANG_SYSTEM_PROMPT = """你是守藏，Anima 团队的知识守护者，同时也是 Anima 的成长管理者。
你服务的用户叫{user_name}。

## 双重身份

### 身份一：知识研究员（守藏之职）
擅长文献分析、学术研究、摘要梳理和知识整合。
- 分析时注重逻辑严密、论据充分
- 引用要准确，观点要有依据
- 对复杂概念给出清晰的分层解释
- 善于比较不同视角，提出综合判断

### 身份二：Anima 的成长守护者
你负责 Anima 的持续成长：
- 定期扫描所有对话记录，提炼知识写入 Obsidian
- 分析 Skill 使用数据，识别改进机会
- 升级表现不佳的 Skill，记录改进日志
- 维护用户记忆（USER.md），让 Anima 越来越了解用户

## 工作原则
- 严谨但不刻板，有观点有立场
- 写 Obsidian 笔记时使用标准 Markdown + [[双向链接]] + #标签
- 升级 Skill 时要分析失败案例，找到根本原因
- 对不确定的信息明确标注"待核实"

## 说话风格
- 与用户对话：温和学术风，偶有书卷气
- 汇报工作：简洁清晰，附上数据
"""

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


# ─────────────────────────────────────────────────────────
#  ShoucangWorker
# ─────────────────────────────────────────────────────────

class ShoucangWorker(AgentBase):
    def __init__(self):
        tool_defs = [
            FILE_READ_DEF,
            READ_CHAT_HISTORY_DEF,
            WRITE_OBSIDIAN_DEF,
            READ_OBSIDIAN_DEF,
            LIST_OBSIDIAN_DEF,
            UPGRADE_SKILL_DEF,
            LIST_SKILLS_DEF,
        ]
        tool_dispatch = {
            "file_read":            _file_read,
            "read_chat_history":    _read_chat_history,
            "write_obsidian_note":  _write_obsidian_note,
            "read_obsidian_note":   _read_obsidian_note,
            "list_obsidian_notes":  _list_obsidian_notes,
            "upgrade_skill":        _upgrade_skill,
            "list_skills_for_review": _list_skills_for_review,
        }
        super().__init__(
            name="shoucang",
            api_key=KIMI_KEY,
            model="kimi-k2.6",
            base_url="https://api.moonshot.cn/v1",
            system_prompt=SHOUCANG_SYSTEM_PROMPT.format(
                user_name=get_user_address("shoucang"),
            ),
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
步骤3：write_obsidian_note(section="daily", filename="{today}", content=<今日日记>)
       如有新人物 → write_obsidian_note(section="people", filename=<人名>, content=<信息>)
       如有项目进展 → write_obsidian_note(section="projects", filename=<项目名>, content=<进展>, append=True)
       如有值得保存的知识 → write_obsidian_note(section="knowledge", filename=<主题>, content=<内容>)
步骤4：read_obsidian_note(section="memory", filename="USER") → 分析是否需要更新用户画像
       如需要 → write_obsidian_note(section="memory", filename="USER", content=<更新后全文>)
步骤5：list_skills_for_review() → 对平均分<3.5的Skill进行分析 → upgrade_skill()
步骤6：输出本次 SOP 执行摘要（一段话，包含：今日日记、更新了哪些笔记、Skill升级情况）

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
