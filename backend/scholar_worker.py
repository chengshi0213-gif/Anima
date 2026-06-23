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
import pref_learning

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

# ── 系统级定时任务（M2a）：每日记忆整理 SOP ──────────────────
# 由 websocket_server 启动流程通过 scheduler.add_task_if_missing 注册，
# _run_agent 收到 agent="shoucang" + 此 prompt 时改走 run_daily_sop()
# （日期感知 + 完成后自带 invalidate_cache），而非通用 run(prompt)。
DAILY_SOP_TASK_NAME = "守藏每日记忆整理"
DAILY_SOP_TRIGGER   = "[SYSTEM] 每日记忆整理 SOP（由 scheduler 04:00 自动触发，调用 run_daily_sop）"
DAILY_SOP_CRON      = "04:00"

# ── 系统级定时任务（M2b）：每周记忆升格 SOP ──────────────────
# 与上面同一套注册模式：_run_agent 收到 agent="shoucang" + 此 prompt 时
# 改走 run_weekly_promotion()（从 L1 事实簇提炼 L2 画像洞察）。
WEEKLY_PROMOTE_TASK_NAME = "守藏每周记忆升格"
WEEKLY_PROMOTE_TRIGGER   = "[SYSTEM] 每周记忆升格 SOP（由 scheduler 周一04:30自动触发，调用 run_weekly_promotion）"
WEEKLY_PROMOTE_CRON      = "30 4 * * 1"

# ── 系统级定时任务（M10）：每周偏好学习 SOP ──────────────────
# 与上面同一套注册模式：_run_agent 收到 agent="shoucang" + 此 prompt 时
# 改走 run_weekly_pref_learning()（从隐式信号里按领域提炼 E 程序层偏好规则）。
WEEKLY_PREF_TASK_NAME = "守藏每周偏好学习"
WEEKLY_PREF_TRIGGER   = "[SYSTEM] 每周偏好学习 SOP（由 scheduler 周一04:45自动触发，调用 run_weekly_pref_learning）"
WEEKLY_PREF_CRON      = "45 4 * * 1"

# ── 系统级定时任务（G1）：每周语体复盘 SOP ──────────────────
# 与 M2b/M10 同一套注册模式。从 lang_profile 的用户语言特征 + 近期消息缓冲
# 产出"她该怎么微调"建议，存回 lang_profile.json，注入 system prompt。
WEEKLY_LANG_TASK_NAME = "守藏每周语体复盘"
WEEKLY_LANG_TRIGGER   = "[SYSTEM] 每周语体复盘 SOP（由 scheduler 周一05:00自动触发，调用 run_weekly_lang_review）"
WEEKLY_LANG_CRON      = "0 5 * * 1"

# ── 系统级定时任务（记忆管家）：每周记忆体检 SOP ──────────────────
# 与上面同一套注册模式：_run_agent 收到 agent="shoucang" + 此 prompt 时
# 改走 run_weekly_memory_audit()（按留存权重自动归档过时 C 层 + 纯重复合并）。
# 用户拍板"全自动静默"：无争议项静默归档（进时间线可回溯，不真删）；
# 矛盾/身份改写的待确认项留待后续阶段（需模型 + 复核队列）。
WEEKLY_AUDIT_TASK_NAME = "守藏每周记忆体检"
WEEKLY_AUDIT_TRIGGER   = "[SYSTEM] 每周记忆体检 SOP（由 scheduler 周一05:15自动触发，调用 run_weekly_memory_audit）"
WEEKLY_AUDIT_CRON      = "15 5 * * 1"

# ── 系统级定时任务（Phase3 子阶段）：每周矛盾巡检 SOP ──────────────────
# 确定性候选发现（bigram Jaccard）→ LLM 裁决真矛盾 → flag_for_confirmation 写入
# memory_reviews 待确认队列。绝不自动改 A/D 类记忆（红线）。
WEEKLY_REVIEW_TASK_NAME = "守藏每周矛盾巡检"
WEEKLY_REVIEW_TRIGGER   = "[SYSTEM] 每周矛盾巡检 SOP（由 scheduler 周一05:30自动触发，调用 run_weekly_review_scan）"
WEEKLY_REVIEW_CRON      = "30 5 * * 1"

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
                                   "project(项目) / note(笔记) / general(其他) / "
                                   "L2(画像洞察，仅每周升格 SOP 使用——从重复出现的 L1 事实里提炼"
                                   "出的'用户是什么样的人'，写入 always-on 画像层)",
                },
                "agent_id": {
                    "type": "string",
                    "description": "这条记忆服务于哪个人格（xi/yiyi/tianyuan/shoucang）。"
                                   "留空=全局，所有人格都可见（用户画像类建议留空）。",
                },
                "importance": {"type": "integer", "description": "重要度 1-5，默认 3"},
                "source_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "仅 category=L2 使用：这条洞察所依据的 L1 事实条目 ID 列表"
                                   "（来自 list_memory 返回的 id），用于审计'她为什么这么认为'。",
                },
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

WRITE_PREF_RULE_DEF = {
    "type": "function",
    "function": {
        "name": "write_pref_rule",
        "description": "写入/更新一条 E 程序层偏好规则（M10，仅每周偏好学习 SOP 使用）。"
                       "规则描述的是「产出该怎么做」（不是用户喜欢什么——那是 B 层），"
                       "按领域分桶，会 always-on 注入工作房间的生成上下文，日常聊天不可见。"
                       "同领域下文本相近的已有规则会被合并更新，不会重复新增；"
                       "单领域规则数超过 8 条会自动淘汰最弱的。",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "领域分桶：文案 / 代码 / PPT / 命盘解读，必须四选一",
                },
                "rule": {
                    "type": "string",
                    "description": "规则正文，第二人称写给'她'自己看的交付物要求，例如"
                                   "'写文案时倾向短句、少用感叹号'。如与用户已声明的偏好"
                                   "（B层）冲突，在规则里加一句自然的提示，不要直接覆盖，"
                                   "例如'你说过喜欢长文案，但最近三次都删到一半，先按短的来'。",
                },
                "source_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "本条规则依据的信号 ID 列表（来自 list_pref_signals 返回的 id），"
                                   "用于审计可追溯。",
                },
                "importance": {"type": "integer", "description": "重要度 1-5，默认 4"},
            },
            "required": ["domain", "rule"],
        },
    },
}

LIST_PREF_SIGNALS_DEF = {
    "type": "function",
    "function": {
        "name": "list_pref_signals",
        "description": "列出某领域下积累的隐式偏好信号（编辑diff/吐槽/采纳），"
                       "用于每周偏好学习 SOP 分析后调用 write_pref_rule 提炼规则。",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "领域分桶：文案 / 代码 / PPT / 命盘解读",
                },
                "limit": {"type": "integer", "description": "最多返回多少条，默认 50"},
            },
            "required": ["domain"],
        },
    },
}

FLAG_CONFIRMATION_DEF = {
    "type": "function",
    "function": {
        "name": "flag_for_confirmation",
        "description": (
            "把一对记忆的疑似矛盾/过时写入待确认队列（memory_reviews），"
            "等用户找机会确认。"
            "【红线】绝不自动修改原记忆，只是提出疑问；"
            "identity_conflict 类（A/D）必须用户点头才能处置。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entry_id_a": {"type": "string", "description": "第一条记忆的 ID"},
                "entry_id_b": {"type": "string", "description": "第二条记忆的 ID"},
                "category":   {"type": "string", "description": "记忆分类（A/B/C/D/L2…）"},
                "conflict_type": {
                    "type": "string",
                    "enum": ["identity_conflict", "possible_contradiction"],
                    "description": "identity_conflict=A/D 类身份/关系，须用户点头；"
                                   "possible_contradiction=其它类，她找机会问",
                },
                "detail": {
                    "type": "string",
                    "description": "一句话说明矛盾点（如：A说工作城市是上海，B说是北京）",
                },
            },
            "required": ["entry_id_a", "entry_id_b", "category", "conflict_type", "detail"],
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
    "L2",   # M2b：画像洞察，仅每周升格 SOP 写入
}


def _remember(key: str, value: str, category: str = "general",
              agent_id: str = None, importance: int = 3,
              source_ids: list = None) -> dict:
    """把事实写入激活的记忆后端（默认 SQLite，无需 Obsidian），下次对话即注入。

    category="L2"（M2b 画像洞察）走 write_l2_insight：自动标来源事实 ID（source_ids）、
    同主题合并为一条而非堆重复，画像层超 L2_MAX_ENTRIES 条时自动淘汰最弱的。
    """
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
        if category == "L2":
            from memory_injector import write_l2_insight
            result = write_l2_insight(key=key, value=value, agent_id=agent_id,
                                      importance=importance, source_ids=source_ids)
            result["category"] = "L2"
            result["agent_id"] = agent_id
            return result
        from memory_injector import write_memory
        eid = write_memory(key=key, value=value, category=category,
                           agent_id=agent_id, importance=importance)
        return {"ok": True, "id": eid, "key": key,
                "category": category, "agent_id": agent_id}
    except Exception as e:
        return {"error": str(e)}


def _flag_for_confirmation(entry_id_a: str, entry_id_b: str,
                           category: str, conflict_type: str, detail: str) -> dict:
    """把一对疑似矛盾记忆写入 memory_reviews 待确认队列（Phase3 子阶段）。
    只存建议，绝不修改原记忆；已有 open 项的对自动去重返回 skipped。"""
    try:
        from memory_injector import get_backend
        backend = get_backend()
        if not hasattr(backend, "add_review"):
            return {"error": "当前后端不支持 memory_reviews"}
        rid = backend.add_review(
            entry_id_a=entry_id_a, entry_id_b=entry_id_b,
            category=category, conflict_type=conflict_type, detail=detail,
        )
        if rid is None:
            return {"ok": True, "status": "skipped", "reason": "已有同对 open 项，去重跳过"}
        return {"ok": True, "review_id": rid, "conflict_type": conflict_type}
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
            WRITE_PREF_RULE_DEF,     # M10：写入 E 程序层偏好规则
            LIST_PREF_SIGNALS_DEF,   # M10：查看某领域积累的隐式偏好信号
            FLAG_CONFIRMATION_DEF,   # Phase3 子阶段：写入矛盾待确认队列
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
                                        kw.get("agent_id"), kw.get("importance", 3),
                                        kw.get("source_ids")),
            "list_memory":          lambda **kw: _list_memory(kw.get("agent_id")),
            "write_pref_rule":      lambda **kw: pref_learning.write_pref_rule(
                                        kw["domain"], kw["rule"], kw.get("source_ids"),
                                        agent_id="xi", importance=kw.get("importance", 4)),
            "list_pref_signals":    lambda **kw: {"signals": pref_learning.get_signals(
                                        kw["domain"], kw.get("limit", 50))},
            "flag_for_confirmation": lambda **kw: _flag_for_confirmation(
                                        kw["entry_id_a"], kw["entry_id_b"],
                                        kw["category"], kw["conflict_type"], kw["detail"]),
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
        # 聊天人格：去 AI 味。只清洗最终回复；Obsidian 笔记走 write_obsidian_note
        # 工具产出，不经此路，Markdown 格式不受影响。
        self.humanize_output = True
        self.temperature = 0.7

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

        # M8 式④（主动想起）：临近到期的 C 层记忆，给今日灵犀当素材
        try:
            from memory_injector import format_due_reminders
            reminders_block = format_due_reminders("xi", within_days=1)
        except Exception:
            reminders_block = ""
        # Phase3 子阶段：待确认的矛盾项，也随今日灵犀找机会问
        try:
            from memory_injector import format_pending_reviews
            reviews_block = format_pending_reviews(max_items=2)
        except Exception:
            reviews_block = ""
        extra_note = ""
        if reminders_block:
            extra_note += (
                f"\n       {reminders_block}\n"
                "       —— 如果上面有内容，找机会在今日灵犀里自然提一句"
                '（比如"对了，明天就是你说的……"），别生硬罗列；没有就不提。\n'
            )
        if reviews_block:
            extra_note += f"\n       {reviews_block}\n"
        reminders_note = extra_note

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
步骤4【今日灵犀——写给用户的日记，本地 Markdown】：
       write_obsidian_note(section="daily", filename="{today}", content=<今日灵犀>)
       <今日灵犀> 是"她"（Anima）写给用户的日记，第一人称"我"，不出现"晞/守藏/陶朱"等内部分工
       名字——对用户来说，今天陪着聊天、改代码、听心事的都只是"我"。
       写法要求（决定这篇日记的质感，务必照做）：
       - 不是工作汇报。禁止"今天做了哪些事/首先.../另外.../总结来说/印象最深的是"这类框架句
         和顺序连接词。
       - 从这一天里还惦记着的一两个真实瞬间写起，可以直接引用用户说过的原话（带引号），写出
         当时"我"在场的感受（陪着、松了口气、心疼、被逗到……），不是事后旁观总结。
       - 几件事之间靠感觉/联想自然带出，不必按"上午/下午/晚上"的时间顺序交代。
       - 句子长短不齐，可以有"对了，你今天……"这种突然想起的小细节，放在后面当轻松一笔。
       - 没什么特别的一天也如实写——"今天挺平的"是好答案，不用硬找"重要时刻"。
       - 结尾一两句轻的关心或告别（如"早点睡。""明天见。"），署名"— Anima"。
       - 篇幅：3~6个自然段，宁短勿长；不堆形容词，不用感叹号、不用网络流行语。

       参考语感（不要照抄，按今天的真实内容写）：
       「还在想你说"终于"的时候，声音很小。
       试了那么久，中间谁都没说话，我也没说话，就那样陪着。听到那一下，我也跟着松了口气。

       咖啡喝了三杯，最后一杯都快一点了，你还说"最后一杯"。
       嗯，你每次都这么说。

       早点睡。
       — Anima」
{reminders_note}
       如有新人物 → write_obsidian_note(section="people", filename=<人名>, content=<信息>)
       如有项目进展 → write_obsidian_note(section="projects", filename=<项目名>, content=<进展>, append=True)
       如有值得保存的知识 → write_obsidian_note(section="knowledge", filename=<主题>, content=<内容>)
步骤5：list_skills_for_review() → 对平均分<3.5的Skill进行分析 → upgrade_skill()
步骤6：输出本次 SOP 执行摘要（一段话，包含：写入了哪些长期记忆、今日灵犀、Skill升级情况）

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

        # M7：归档超时 C 状态层记忆
        try:
            from memory_injector import run_archival
            run_archival()
        except Exception:
            pass

        # SOP 完成后使记忆缓存失效（让下次对话读取最新记忆）
        try:
            from memory_injector import invalidate_cache
            invalidate_cache()
        except Exception:
            pass

        return result

    def run_weekly_promotion(self, progress_cb=None) -> dict:
        """
        每周升格 SOP（M2b）：从近期积累的 L1 事实条目（B/C/D 层）里，
        用 LLM 提炼出"画像洞察"（L2，标来源事实 ID），写入 always-on 画像层。
        画像层条数上限由 write_l2_insight 内部维护（≤12，超出按重要度+新近度淘汰）。

        由定时任务每周一 04:30 调用，也可手动触发。
        progress_cb: 可选回调 fn(step, total, msg)，用于前端进度推送
        """
        import asyncio
        from memory_injector import list_memory, L2_SOURCE_SEP

        def _cb(step, total, msg):
            if progress_cb:
                try:
                    progress_cb(step, total, msg)
                except Exception:
                    pass

        _cb(0, 3, "开始每周记忆升格...")

        l1_entries = [e for e in list_memory("xi") if e.category in ("B", "C", "D")]
        l2_entries = [e for e in list_memory("xi") if e.category == "L2"]

        if not l1_entries:
            _cb(3, 3, "本周没有可升格的 L1 事实，跳过")
            return {"status": "skipped", "summary": "本周没有可升格的 L1 事实，跳过升格"}

        facts_block = "\n".join(
            f"- [{e.id}] ({e.category}) {e.key}：{e.value}" for e in l1_entries
        )
        insights_block = "\n".join(
            f"- {e.key}：{e.value.split(L2_SOURCE_SEP)[0]}"
            + ("（命理先验，待验证，importance={}）".format(e.importance) if e.importance <= 2 else "")
            for e in l2_entries
        ) or "（暂无）"

        prompt = f"""请执行每周记忆升格 SOP：从下面的 L1 事实条目里，提炼出能体现"用户是什么样的人"的
画像洞察（L2），帮助 Anima 更懂用户、调整相处方式。

【L1 事实条目（共 {len(l1_entries)} 条，格式：[事实ID] (分类) 标题：内容）】
{facts_block}

【已有的 L2 画像洞察】
{insights_block}

要求：
1. 只有当多条事实呈现出**重复出现的模式**（同一类行为/状态出现 2 次及以上）时才提炼为洞察；
   单次/偶发的事实不要升格，留在 L1 即可。
2. 每条洞察用 remember(category="L2", key=<简短标题>, value=<一句话洞察>, importance=4,
   agent_id="xi", source_ids=[<引用的事实ID>...]) 写入；value 用客观、留有余地的措辞
   （"似乎""倾向于"），不要武断下结论。
3. 已有的 L2 洞察如果被新事实印证或修正，用同样的 key 重新 remember 更新它（系统会自动
   合并，不会重复）；不要为同一个主题反复造新 key。
3b. 标了"（命理先验，待验证）"的洞察是命盘解读时记下的初步判断（M9）。本周事实如果与它吻合，
   用同样的 key 重新 remember，把措辞从"我猜……"改得更确定一些，并把 importance 提到 4；
   如果相悖，则修正 value（自然地说"看来和盘面猜的不太一样"），importance 仍可先维持低位，
   等下次再验证。不要放着不管。
4. 画像层总条数上限 12 条（系统会自动淘汰超出的，但你应优先合并而不是无脑新增）。
5. 如果 L1 事实里没有任何重复模式，不要勉强升格，直接结束，不调用 remember。
6. 完成后输出一段话总结：本次升格新增/更新了哪些洞察、各自依据哪些事实 ID。"""

        _cb(1, 3, "守藏正在分析近期记忆...")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.run(prompt))
        finally:
            loop.close()

        _cb(2, 3, "升格完成，刷新缓存...")

        try:
            from memory_injector import invalidate_cache
            invalidate_cache()
        except Exception:
            pass

        _cb(3, 3, "每周升格完成")
        return result

    def run_weekly_memory_audit(self, progress_cb=None) -> dict:
        """每周记忆体检 SOP（记忆管家）：纯确定性、不调模型。

        用户拍板"全自动静默"——无争议项静默处理，且全部进演化时间线可回溯（不真删）：
          1. 过时归档：超时未访问的 C 状态层记忆，移进时间线。
          2. 纯重复合并：同分类下规整后内容完全一致的近重复，每簇留留存权重最高的一条，
             其余移进时间线（reason='merge'）。
        语义相近但不全等的（可能是矛盾/细微差别）**不动**——留给后续"待确认项"阶段
        （需模型 + 复核队列；守红线：矛盾、身份/关系类改写一律转用户确认）。

        由定时任务每周一 05:15 调用，也可手动触发。
        progress_cb: 可选回调 fn(step, total, msg)。
        """
        from memory_injector import get_backend, invalidate_cache

        def _cb(step, total, msg):
            if progress_cb:
                try:
                    progress_cb(step, total, msg)
                except Exception:
                    pass

        _cb(0, 3, "开始每周记忆体检...")
        backend = get_backend()

        _cb(1, 3, "归档过时的近期状态...")
        archived: list[str] = []
        if hasattr(backend, "archive_stale_c_layer"):
            try:
                archived = backend.archive_stale_c_layer()
            except Exception:
                archived = []

        _cb(2, 3, "合并纯重复记忆...")
        merges: list[dict] = []
        if hasattr(backend, "merge_near_duplicates"):
            try:
                merges = backend.merge_near_duplicates()
            except Exception:
                merges = []

        try:
            invalidate_cache()
        except Exception:
            pass

        merged_count = sum(len(m.get("archived", [])) for m in merges)
        summary = f"记忆体检完成：归档过时 {len(archived)} 条，合并纯重复 {merged_count} 条。"
        _cb(3, 3, summary)
        return {"status": "ok", "summary": summary,
                "archived": archived, "merged": merges}

    def run_weekly_pref_learning(self, progress_cb=None) -> dict:
        """
        每周偏好学习 SOP（M10）：从工作房间积累的隐式信号（编辑diff/吐槽/采纳）里，
        按领域分桶用 LLM 提炼出"产出该怎么做"的 E 程序层偏好规则，写入 pref_rules
        （≤8条/领域），always-on 注入工作房间生成上下文（日常房间不注入）。

        由定时任务每周一 04:45 调用（紧跟 M2b 的 04:30），也可手动触发。
        progress_cb: 可选回调 fn(step, total, msg)，用于前端进度推送
        """
        import asyncio

        def _cb(step, total, msg):
            if progress_cb:
                try:
                    progress_cb(step, total, msg)
                except Exception:
                    pass

        _cb(0, 3, "开始每周偏好学习...")

        counts = pref_learning.get_signal_counts()
        eligible = [d for d, n in counts.items() if n >= pref_learning.MIN_SIGNALS_PER_DOMAIN]

        if not eligible:
            _cb(3, 3, "本周各领域信号数量都不足，跳过偏好学习")
            return {"status": "skipped",
                    "summary": f"本周各领域信号数量都不足（每领域需≥{pref_learning.MIN_SIGNALS_PER_DOMAIN}条），跳过偏好学习"}

        existing_rules = pref_learning.get_pref_rules()
        rules_block = "\n".join(
            f"- [{r['domain']}] {r['rule']}" for r in existing_rules
        ) or "（暂无）"

        try:
            from memory_injector import list_memory
            b_entries = [e for e in list_memory("xi") if e.category == "B"]
            b_block = "\n".join(f"- {e.key}：{e.value}" for e in b_entries) or "（暂无）"
        except Exception:
            b_block = "（暂无）"

        domains_block = "、".join(eligible)

        prompt = f"""请执行每周偏好学习 SOP：从用户在工作房间留下的隐式信号里（编辑diff/吐槽/采纳），
按领域提炼出"产出该怎么做"的 E 程序层偏好规则，帮助 Anima 下次直接按用户要的样子来。

【本周信号量达标的领域（≥{pref_learning.MIN_SIGNALS_PER_DOMAIN}条）】
{domains_block}

【已有的 E 程序层规则】
{rules_block}

【用户已声明的偏好（B层，供冲突检测参考）】
{b_block}

请按以下步骤逐个领域处理：
1. 对上面每个达标领域，调用 list_pref_signals(domain=<领域>) 查看该领域的信号
   （编辑diff signal_type="edit" 的 original/edited 最重要——是"产出A→改成B"的真实证据；
   吐槽 signal_type="complaint" 是负样本+原因；采纳 signal_type="accept" 是弱正信号）。
2. 只有当多条信号呈现出**重复出现的模式**才提炼为规则；单次/偶发的不要提炼。
3. 每条规则用 write_pref_rule(domain=<领域>, rule=<一句话规则>, source_ids=[<信号ID>...],
   importance=4) 写入；规则要写成"怎么做"的指令，不是"用户喜欢什么"的描述。
4. 规则按领域分桶，互不影响——文案领域的规则不要写进代码领域，反之亦然。
5. 如果某条新规则与上面【B层】的某条偏好冲突，仍按新规则写（E为准），但在 rule 文本里
   自然提示一句（参考："你说过喜欢长文案，但最近几次都改成短的，先按短的来，想换回来告诉我"），
   不要静默覆盖、也不要回避冲突。
6. 单领域规则数上限 8 条（系统会自动淘汰超出的，但你应优先合并相近规则而不是无脑新增）。
7. 信号量不达标的领域跳过，不要勉强提炼。
8. 完成后输出一段话总结：本次新增/更新了哪些规则、各自属于哪个领域、依据哪些信号 ID。"""

        _cb(1, 3, "守藏正在分析本周偏好信号...")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.run(prompt))
        finally:
            loop.close()

        _cb(2, 3, "偏好学习完成，刷新缓存...")

        try:
            from memory_injector import invalidate_cache
            invalidate_cache()
        except Exception:
            pass

        _cb(3, 3, "每周偏好学习完成")
        return result

    def run_weekly_lang_review(self, progress_cb=None) -> dict:
        """
        每周语体复盘 SOP（G1）：从 lang_profile 积累的用户语言特征 + 近期消息样本里，
        用 LLM 产出"她该怎么微调"建议（而非"用户什么样"），存回 lang_profile.json，
        下次对话时通过 get_profile_block() 注入 system prompt。

        由定时任务每周一 05:00 调用（紧跟 M2b 04:30 + M10 04:45），也可手动触发。
        """
        import asyncio
        import lang_profile as lp

        def _cb(step, total, msg):
            if progress_cb:
                try:
                    progress_cb(step, total, msg)
                except Exception:
                    pass

        _cb(0, 3, "开始每周语体复盘...")

        status = lp.get_status()
        feat = status.get("features", {})
        count = status.get("message_count", 0)

        if not feat or count < lp.UPDATE_EVERY:
            _cb(3, 3, "消息样本不足，跳过语体复盘")
            return {"status": "skipped",
                    "summary": f"消息样本不足（{count}<{lp.UPDATE_EVERY}），跳过语体复盘"}

        data = lp._load()
        buf = data.get("buffer", [])
        sample = buf[-20:] if len(buf) > 20 else buf
        sample_block = "\n".join(f"- {m[:80]}" for m in sample) or "（无）"

        feat_block = json.dumps(feat, ensure_ascii=False, indent=2)

        prompt = f"""请执行每周语体复盘：根据下面的用户语言特征和近期消息样本，
产出 Anima 本周该怎么微调自己的说话方式。

【用户语言特征（{count} 条消息统计）】
{feat_block}

【近期消息样本（最近 {len(sample)} 条的开头）】
{sample_block}

要求：
1. 遵守三成原则：形式上向用户靠近三成，七成保持 Anima 自己。
   - 用户短句多 → Anima 适度精简，但不丢她的节奏感
   - 用户常用 emoji → Anima 偶尔回一个，不先抛不刷屏
   - 用户中英混 → Anima 可以偶尔用对方常用的术语，但不刻意中英混说
2. 禁区绝对不碰：脏话不跟、火星文不跟、叠字卖萌不跟、Anima 的标点纪律不破。

请严格按下面两段格式输出，两段都要有，用方括号标题分隔：

【微调建议】
2-4 条"她该怎么微调"的语体建议（不是"用户什么样"的描述）。每条一句话，用"你可以……"
或"适度……"开头。如果风格没明显变化、已有建议仍合适，本段只写"本周无需调整"。

【表达习惯】
2-3 条对"他怎么组织一段话"的观察（语义纹理，比口头禅更深一层）。比如：先抛结论再解释 /
习惯先铺背景再说事 / 用反问表达不满 / 爱举具体例子 / 喜欢自问自答。每条一句话、客观描述他。
这是帮 Anima 更懂他、接得住他，不是要她模仿；若没有稳定习惯，本段只写"暂不明显"。"""

        _cb(1, 3, "守藏正在复盘语体...")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.run(prompt))
        finally:
            loop.close()

        _cb(2, 3, "语体复盘完成，保存建议...")

        raw = ""
        if isinstance(result, dict):
            raw = result.get("reply", result.get("summary", ""))
        elif isinstance(result, str):
            raw = result
        # 切出【微调建议】+【表达习惯（语义纹理）】两段，分别落库
        advice_text, texture_text = lp.parse_review_output(raw)
        if advice_text and "本周无需调整" not in advice_text:
            lp.save_llm_advice(advice_text.strip())
        if texture_text and "暂不明显" not in texture_text:
            lp.save_texture(texture_text.strip())

        _cb(3, 3, "每周语体复盘完成")
        return result

    def run_weekly_review_scan(self, progress_cb=None) -> dict:
        """每周矛盾巡检 SOP（Phase3 子阶段）：
        确定性候选发现（bigram Jaccard）→ LLM 裁决哪些是真矛盾 →
        调 flag_for_confirmation 工具写入待确认队列。
        绝不自动修改/删除原记忆（红线）；由"她"找机会问用户。

        由定时任务每周一 05:30 调用（紧跟记忆体检 05:15），也可手动触发。
        """
        import asyncio
        from memory_injector import get_backend

        def _cb(step, total, msg):
            if progress_cb:
                try:
                    progress_cb(step, total, msg)
                except Exception:
                    pass

        _cb(0, 3, "开始每周矛盾巡检...")
        backend = get_backend()

        if not hasattr(backend, "find_review_candidates"):
            _cb(3, 3, "当前后端不支持矛盾巡检，跳过")
            return {"status": "skipped", "summary": "当前后端不支持 find_review_candidates"}

        candidates = backend.find_review_candidates()

        if not candidates:
            _cb(3, 3, "本周无矛盾候选，跳过")
            return {"status": "skipped", "summary": "本周没有发现疑似矛盾的记忆对，无需巡检"}

        cand_block = "\n".join(
            f"[{i+1}] entry_id_a={c['entry_id_a']} key_a={c['key_a']!r} value_a={c['value_a']!r}\n"
            f"    entry_id_b={c['entry_id_b']} key_b={c['key_b']!r} value_b={c['value_b']!r}\n"
            f"    category={c['category']} conflict_type={c['conflict_type']} similarity={c['similarity']}"
            for i, c in enumerate(candidates)
        )

        prompt = f"""请执行每周矛盾巡检 SOP：从下面的候选记忆对里，判断哪些是真正的矛盾/过时，
并用 flag_for_confirmation 工具写入待确认队列。

【候选记忆对（共 {len(candidates)} 对，由 bigram 相似度检测出，尚未判断是否真矛盾）】
{cand_block}

要求：
1. 逐对检查——相似但不矛盾的（比如同一件事的不同角度）直接跳过，不 flag。
   只有确实描述了同一件事但结论相反/明显过时的才 flag。
2. 对每个真矛盾/过时对，调用：
   flag_for_confirmation(
       entry_id_a=<A的id>, entry_id_b=<B的id>,
       category=<分类>, conflict_type=<'identity_conflict'或'possible_contradiction'>,
       detail=<一句话说明矛盾点，例：A说城市是上海，B说是北京>
   )
3. 【红线】绝不调用 remember() 修改原记忆——这里只是提出疑问，等用户确认。
   identity_conflict 类（A/D 类身份/关系）尤其重要，不能擅自改。
4. 如果候选里没有真矛盾，直接说"本周未发现真矛盾"，不调任何工具。
5. 完成后输出一段话总结：flag 了几对（如果有），各自是什么矛盾点。"""

        _cb(1, 3, "守藏正在裁决候选矛盾对...")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.run(prompt))
        finally:
            loop.close()

        _cb(2, 3, "矛盾巡检完成，刷新缓存...")
        try:
            from memory_injector import invalidate_cache
            invalidate_cache()
        except Exception:
            pass

        _cb(3, 3, "每周矛盾巡检完成")
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
