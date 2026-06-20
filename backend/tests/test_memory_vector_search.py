#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_memory_vector_search.py — 语义检索 / 混合召回（M4）单元测试

用 monkeypatch 假埋一个基于"话题关键词"的伪 embedding（测试环境无真实
bge-small 模型文件），验证：
  - write() 在 embedding 可用时写入 memory_vectors
  - search() = FTS5 ∪ 余弦相似度，换种说法（无关键词重合）也能召回
  - FTS5 与向量召回结果合并去重
  - delete() 同步清理向量
  - embedding 不可用时自动降级回纯 FTS5，不报错

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_memory_vector_search.py -v
"""
from __future__ import annotations

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


def test_write_stores_vector_when_embedding_available(sqlite_mem):
    eid = sqlite_mem.write("下周行程", "周三去上海出差", category="C", agent_id="xi")
    with sqlite_mem._conn() as conn:
        row = conn.execute(
            "SELECT * FROM memory_vectors WHERE entry_id=?", [eid]
        ).fetchone()
    assert row is not None
    assert row["dim"] == len(_TOPICS)


def test_semantic_recall_without_keyword_overlap(sqlite_mem):
    sqlite_mem.write("下周行程", "周三去上海出差", category="C", agent_id="xi")

    # FTS5/LIKE 对这个问法应当召不回（无字面重合）
    fts_only = sqlite_mem._fts_search("最近有旅行计划吗", agent_id="xi")
    assert not any(e.key == "下周行程" for e in fts_only)

    # 混合检索：同话题（旅行）应能语义召回
    results = sqlite_mem.search("最近有旅行计划吗", agent_id="xi")
    assert any(e.key == "下周行程" for e in results)


def test_fts_and_vector_results_are_deduped(sqlite_mem):
    sqlite_mem.write("出差安排", "周三去上海出差", category="C", agent_id="xi")
    results = sqlite_mem.search("上海出差", agent_id="xi")
    ids = [e.id for e in results]
    assert len(ids) == len(set(ids))
    assert any(e.key == "出差安排" for e in results)


def test_unrelated_topic_not_recalled(sqlite_mem):
    sqlite_mem.write("猫粮品牌", "现在吃馋不腻", category="B", agent_id="xi")
    results = sqlite_mem.search("最近有旅行计划吗", agent_id="xi")
    assert not any(e.key == "猫粮品牌" for e in results)


def test_delete_removes_vector(sqlite_mem):
    eid = sqlite_mem.write("临时备注", "随便记一条", category="C", agent_id="xi")
    assert sqlite_mem.delete(eid) is True
    with sqlite_mem._conn() as conn:
        row = conn.execute(
            "SELECT * FROM memory_vectors WHERE entry_id=?", [eid]
        ).fetchone()
    assert row is None


def test_degrades_to_fts_when_embedding_unavailable(sqlite_mem, monkeypatch):
    monkeypatch.setattr(memory_embed, "is_available", lambda: False)
    monkeypatch.setattr(memory_embed, "embed_texts", lambda texts: None)

    # 写入不报错，且不产生向量记录
    eid = sqlite_mem.write("下周行程", "周三去上海出差", category="C", agent_id="xi")
    with sqlite_mem._conn() as conn:
        row = conn.execute(
            "SELECT * FROM memory_vectors WHERE entry_id=?", [eid]
        ).fetchone()
    assert row is None

    # 关键词命中仍正常（纯 FTS5/LIKE）
    results = sqlite_mem.search("上海出差", agent_id="xi")
    assert any(e.key == "下周行程" for e in results)

    # 语义召回不可用时不报错，只是召不回
    results2 = sqlite_mem.search("最近有旅行计划吗", agent_id="xi")
    assert isinstance(results2, list)
    assert not any(e.key == "下周行程" for e in results2)
