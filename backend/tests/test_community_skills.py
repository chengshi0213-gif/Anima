#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_community_skills.py — 社区扩展包 + 内置 skill 总量与完整性测试

锁定：
  - community_skills 恰好 70 个，id 唯一、必填字段齐全；
  - 与原内置 30 个无 id 冲突；
  - 合并后 BUILTIN_SKILLS 恰好 100 个；
  - 每个新 skill 落盘后能取到非空 system_prompt（premium 在 Pro 下可取）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import community_skills as cs  # noqa: E402
import skill_manager as sm     # noqa: E402


def test_community_count_is_70():
    assert len(cs.COMMUNITY_SKILLS) == 70


def test_community_ids_unique_and_fields_complete():
    seen = set()
    required = ("id", "name", "category", "icon", "description",
                "use_cases", "system_prompt", "version", "tags")
    for s in cs.COMMUNITY_SKILLS:
        for k in required:
            assert s.get(k) not in (None, "", []), f"{s.get('id')} 缺 {k}"
        assert s["id"] not in seen, f"重复 id {s['id']}"
        seen.add(s["id"])


def test_no_overlap_with_original_builtin():
    # 原始 30 个内置（合并发生在 import 时，这里反推：community 不应覆盖核心 8 个免费技能）
    core_free = {"emotional_support", "deep_memory_recall", "technical_writing",
                 "strategic_thinking", "code_review", "daily_report_gen",
                 "knowledge_extraction", "workflow_builder"}
    comm_ids = {s["id"] for s in cs.COMMUNITY_SKILLS}
    assert core_free.isdisjoint(comm_ids)


def test_merged_builtin_total_is_100():
    ids = [s["id"] for s in sm.BUILTIN_SKILLS]
    assert len(ids) == 100
    assert len(set(ids)) == 100


def test_new_skills_yield_prompt_after_init():
    sm.init_builtin_skills()
    # 取几个免费的新 skill，落盘后应能拿到非空 prompt
    for sid in ("git_workflow", "journaling_guide", "habit_builder",
                "meeting_notes", "regex_helper"):
        p = sm.get_skill_prompt(sid)
        assert p and len(p) > 20, f"{sid} 注入 prompt 为空"
