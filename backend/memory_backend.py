#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_backend.py — 记忆后端抽象层

SQLiteMemoryBackend 和 ObsidianMemoryBackend 都实现这个接口，
保证两种存储方式向 Agent 提供格式完全一致的记忆注入文本。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ── 数据模型 ─────────────────────────────────────────────────────
@dataclass
class MemoryEntry:
    id: str
    agent_id: Optional[str]     # None = 全局（所有 Agent 共享）
    category: str               # user_profile | preference | emotional |
                                # business | knowledge | writing_style |
                                # project | note | general
    key: str
    value: str
    importance: int = 3         # 1=低  3=中  5=高
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def to_dict(self) -> dict:
        return {
            "id": self.id, "agent_id": self.agent_id,
            "category": self.category, "key": self.key,
            "value": self.value, "importance": self.importance,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


# ── 每个 Agent 关注的记忆分类 ─────────────────────────────────────
AGENT_MEMORY_CATEGORIES: dict[str, list[str]] = {
    "xi":   ["user_profile", "preference", "note", "general"],
    "yiyi":     ["user_profile", "emotional", "general"],
    "tianyuan": ["user_profile", "business", "project", "general"],
    "shoucang":  ["user_profile", "knowledge", "note", "general"],
    "executor": ["user_profile", "general"],
    "writer":   ["user_profile", "writing_style", "general"],
    "reader":   ["user_profile", "general"],
    "critic":   ["user_profile", "general"],
}

CATEGORY_LABELS: dict[str, str] = {
    "user_profile":  "用户画像",
    "preference":    "偏好设置",
    "emotional":     "情感记录",
    "business":      "创业背景",
    "knowledge":     "知识背景",
    "writing_style": "写作风格",
    "project":       "项目上下文",
    "note":          "笔记",
    "general":       "其他记忆",
}

# ── 注入模板（两个后端共用，保证质量一致）─────────────────────────
INJECTION_TEMPLATES: dict[str, str] = {
    "xi": (
        "## 关于用户的记忆\n{memory}\n\n"
        "请自然融入这些记忆，像真正认识用户的朋友一样说话。"
        "不需要刻意说「我记得你…」。"
    ),
    "yiyi": (
        "## 关于这个人的记忆\n{memory}\n\n"
        "这些是你们之间积累的了解，"
        "请用温柔自然的方式体现出来，不要说「根据记录」。"
    ),
    "tianyuan": (
        "## 用户背景与目标\n{memory}\n\n"
        "结合这位创业者的实际情况，给出有针对性的策略。"
    ),
    "shoucang": (
        "## 用户知识背景\n{memory}\n\n"
        "根据用户的知识背景调整解释深度，避免重复已知内容。"
    ),
}
DEFAULT_INJECTION = "## 用户背景\n{memory}"


# ── 抽象基类 ─────────────────────────────────────────────────────
class MemoryBackend(ABC):
    """
    记忆后端统一接口。
    子类实现存储逻辑，门面层（memory_injector.py）决定用哪个后端。
    """

    # ── 核心操作 ─────────────────────────────────────────────────

    @abstractmethod
    def read_for_agent(self, agent_id: str, max_chars: int = 1500) -> str:
        """返回注入到 system prompt 的格式化记忆文本"""

    @abstractmethod
    def write(self,
              key: str,
              value: str,
              category: str = "general",
              agent_id: Optional[str] = None,
              importance: int = 3) -> str:
        """写入一条记忆，返回 entry id（同 key 则更新）"""

    @abstractmethod
    def search(self,
               query: str,
               agent_id: Optional[str] = None,
               limit: int = 10) -> list[MemoryEntry]:
        """关键词搜索记忆"""

    @abstractmethod
    def list_all(self,
                 agent_id: Optional[str] = None,
                 limit: int = 200) -> list[MemoryEntry]:
        """列出全部记忆（按重要度降序）"""

    @abstractmethod
    def delete(self, entry_id: str) -> bool:
        """删除一条记忆"""

    # ── 迁移接口 ─────────────────────────────────────────────────

    @abstractmethod
    def export_snapshot(self) -> dict:
        """导出全量数据为可序列化字典，用于跨后端迁移"""

    @abstractmethod
    def import_snapshot(self, data: dict, merge: bool = True) -> int:
        """
        导入快照。
        merge=True: INSERT OR IGNORE（保留已有数据）
        merge=False: INSERT OR REPLACE（覆盖）
        返回成功导入的条数。
        """

    @abstractmethod
    def get_backend_type(self) -> str:
        """返回 'sqlite' 或 'obsidian'"""

    @abstractmethod
    def get_status(self) -> dict:
        """返回后端状态信息（用于前端展示）"""

    # ── 共用格式化逻辑（子类可直接调用）─────────────────────────

    def _format_injection(self,
                          agent_id: str,
                          entries: list[MemoryEntry],
                          max_chars: int = 1500) -> str:
        """将 MemoryEntry 列表格式化成统一的注入文本"""
        if not entries:
            return ""

        # 按 category 分组，重要度排序
        groups: dict[str, list[MemoryEntry]] = {}
        for e in sorted(entries, key=lambda x: -x.importance):
            groups.setdefault(e.category, []).append(e)

        parts: list[str] = []
        for cat, items in groups.items():
            label = CATEGORY_LABELS.get(cat, cat)
            lines = [f"- {e.key}：{e.value}" for e in items]
            parts.append(f"[{label}]\n" + "\n".join(lines))

        combined = "\n\n".join(parts)
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n…[记忆已截断]"

        template = INJECTION_TEMPLATES.get(agent_id, DEFAULT_INJECTION)
        return template.format(memory=combined)
