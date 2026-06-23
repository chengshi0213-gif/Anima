#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_memory_topic_injection.py — 话题感知注入 / 复合分排序（M5）单元测试

用 monkeypatch 假埋一个基于"话题关键词"的伪 embedding（同 M4），验证：
  - 分层预算：画像层 always-on + 话题相关(复合分排序) + 高重要性兜底
  - 切换话题（query）会改变"[相关记忆]"内的排序/收录，不再是静态 importance Top-N
  - 调试输出（DEBUG 日志）能看到 相关性/新近度/重要性/复合分 分项得分
  - 高重要性条目即使话题不匹配，也能通过兜底层被收录
  - embedding 不可用 / query 为空时优雅降级，不报错

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_memory_topic_injection.py -v
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import memory_embed  # noqa: E402
import memory_injector as mi  # noqa: E402
from memory_sqlite import SQLiteMemoryBackend  # noqa: E402

_TOPICS = (
    ("旅行", ("上海", "出差", "旅行")),
    ("宠物", ("猫", "宠物", "猫粮")),
    ("工作", ("项目", "工作", "方案")),
)


def _fake_embed(texts: list[str]) -> np.ndarray:
    vecs = []
    for t in texts:
        v = np.zeros(len(_TOPICS), dtype=np.float32)
        for i, (_name, keywords) in enumerate(_TOPICS):
            if any(k in t for k in keywords):
                v[i] = 1.0
        n = np.linalg.norm(v)
        vecs.append(v / n if n > 0 else v)
    return np.array(vecs, dtype=np.float32)


def _fake_cosine(q: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    if matrix.shape[0] == 0:
        return np.empty((0,), dtype=np.float32)
    qn = np.linalg.norm(q) + 1e-9
    mn = np.linalg.norm(matrix, axis=1) + 1e-9
    return (matrix @ q) / (mn * qn)


@pytest.fixture(autouse=True)
def sqlite_mem(tmp_path, monkeypatch):
    backend = SQLiteMemoryBackend(tmp_path / "mem.db")
    monkeypatch.setattr(mi, "_backend", backend)
    monkeypatch.setattr(memory_embed, "embed_texts", _fake_embed)
    monkeypatch.setattr(memory_embed, "cosine_sim", _fake_cosine)
    monkeypatch.setattr(memory_embed, "is_available", lambda: True)
    mi.invalidate_cache()
    mi.reset_session_writes()
    yield backend
    mi.invalidate_cache()
    mi.reset_session_writes()


def test_topic_relevant_order_changes_with_query(sqlite_mem):
    sqlite_mem.write("下周行程", "周三去上海出差", category="C", agent_id="xi", importance=3)
    sqlite_mem.write("猫粮品牌", "新买了猫粮", category="B", agent_id="xi", importance=3)

    travel = mi.get_memory_injection("xi", query="最近有旅行计划吗")
    pet = mi.get_memory_injection("xi", query="猫粮怎么选")

    assert "[相关记忆]" in travel and "[相关记忆]" in pet
    assert travel.index("下周行程") < travel.index("猫粮品牌")
    assert pet.index("猫粮品牌") < pet.index("下周行程")


def test_profile_layer_always_present_regardless_of_topic(sqlite_mem):
    sqlite_mem.write("称呼", "可以喊我阿狸", category="A", agent_id="xi", importance=5)
    sqlite_mem.write("下周行程", "周三去上海出差", category="C", agent_id="xi", importance=3)

    for q in ("最近有旅行计划吗", "猫粮怎么选", ""):
        injection = mi.get_memory_injection("xi", query=q)
        assert "[画像]" in injection
        assert "称呼" in injection


def test_debug_log_exposes_score_breakdown(sqlite_mem, caplog):
    sqlite_mem.write("下周行程", "周三去上海出差", category="C", agent_id="xi", importance=3)
    sqlite_mem.write("猫粮品牌", "新买了猫粮", category="B", agent_id="xi", importance=3)

    with caplog.at_level(logging.DEBUG, logger="memory_injector"):
        mi.get_memory_injection("xi", query="最近有旅行计划吗")

    msgs = [r.getMessage() for r in caplog.records if "记忆注入" in r.getMessage()]
    assert msgs, "应输出每条候选记忆的分项得分"
    assert all("相关性=" in m and "留存=" in m and "来源=" in m
               and "新近度=" in m and "复合分=" in m for m in msgs)


def test_high_importance_entry_recovered_via_fallback(sqlite_mem):
    # 写入大量旅行话题条目，占满"话题相关"预算（每条约 69 字 × 20 ≈ 1380 字 > 900 预算）
    for i in range(20):
        sqlite_mem.write(f"旅行细节{i:02d}", "上海出差安排" * 10, category="C", agent_id="xi", importance=3)

    # 写入一条与"旅行"话题无关、但 importance=5 的重要记忆
    sqlite_mem.write("过敏史", "对青霉素过敏，就医务必告知", category="D", agent_id="xi", importance=5)

    injection = mi.get_memory_injection("xi", query="最近有旅行计划吗")
    assert "[重要提醒]" in injection
    assert "过敏史" in injection


def test_degrades_gracefully_without_embedding(sqlite_mem, monkeypatch):
    monkeypatch.setattr(memory_embed, "is_available", lambda: False)
    monkeypatch.setattr(memory_embed, "embed_texts", lambda texts: None)

    sqlite_mem.write("下周行程", "周三去上海出差", category="C", agent_id="xi", importance=3)
    sqlite_mem.write("猫粮品牌", "新买了猫粮", category="B", agent_id="xi", importance=3)

    injection = mi.get_memory_injection("xi", query="最近有旅行计划吗")
    assert "下周行程" in injection
    assert "猫粮品牌" in injection


def test_empty_query_backward_compatible(sqlite_mem):
    sqlite_mem.write("称呼", "可以喊我阿狸", category="A", agent_id="xi", importance=5)
    sqlite_mem.write("下周行程", "周三去上海出差", category="C", agent_id="xi", importance=3)

    injection = mi.get_memory_injection("xi")
    assert "称呼" in injection
    assert "下周行程" in injection
