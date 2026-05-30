#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_kb_agent.py — 知识库「按 agent 分库」可见性 单元测试 (pytest)

不触网：stub 掉 Qwen Embedding，用确定性向量验证分库过滤逻辑。
规则（见 knowledge_base._agent_visible）：
  - 共享语料(agent_id=None) 对所有人可见
  - 私有语料 仅其拥有者可见
  - 无 agent 的检索 只看共享语料（防跨 agent 泄露）

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_kb_agent.py -v
"""
from __future__ import annotations

import sys
import hashlib
from pathlib import Path

import numpy as np
import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import knowledge_base as kbmod  # noqa: E402


def _fake_embed(texts):
    """确定性假 embedding：按文本 hash 生成稳定向量。"""
    out = []
    for t in texts:
        h = hashlib.sha256(t.encode("utf-8")).digest()
        seed = int.from_bytes(h[:4], "big")
        rng = np.random.RandomState(seed)
        out.append(rng.rand(kbmod.EMBED_DIM).astype(np.float32))
    return np.array(out, dtype=np.float32)


@pytest.fixture
def kb(tmp_path, monkeypatch):
    # 隔离存储到 tmp，stub embedding
    monkeypatch.setattr(kbmod, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(kbmod, "VECTORS_FILE", tmp_path / "vectors.npz")
    monkeypatch.setattr(kbmod, "_embed", _fake_embed)
    inst = kbmod.KnowledgeBase()
    inst.ingest("公司全员共享的入职手册内容", "handbook", doc_id="shared1", agent_id=None)
    inst.ingest("晞专属命理紫微斗数排盘知识", "ziwei", doc_id="yiyi1", agent_id="yiyi")
    inst.ingest("陶朱专属创业商业计划书", "biz", doc_id="ty1", agent_id="tianyuan")
    return inst


def test_search_yiyi_sees_own_plus_shared(kb):
    hits = kb.search("内容", top_k=10, agent_id="yiyi")
    docs = {h["doc_id"] for h in hits}
    assert "yiyi1" in docs
    assert "shared1" in docs
    assert "ty1" not in docs   # 不能看到陶朱私有


def test_search_tianyuan_isolated(kb):
    hits = kb.search("内容", top_k=10, agent_id="tianyuan")
    docs = {h["doc_id"] for h in hits}
    assert "ty1" in docs and "shared1" in docs
    assert "yiyi1" not in docs


def test_search_no_agent_shared_only(kb):
    hits = kb.search("内容", top_k=10, agent_id=None)
    docs = {h["doc_id"] for h in hits}
    assert docs == {"shared1"}   # 无 agent 检索只见共享语料


def test_list_docs_filtering(kb):
    all_docs = {d["doc_id"] for d in kb.list_docs()}
    assert all_docs == {"shared1", "yiyi1", "ty1"}   # 管理视图：全部
    yiyi_docs = {d["doc_id"] for d in kb.list_docs("yiyi")}
    assert yiyi_docs == {"shared1", "yiyi1"}
    yiyi_only = {d["doc_id"] for d in kb.list_docs("yiyi", include_shared=False)}
    assert yiyi_only == {"yiyi1"}


def test_ingest_skill_references_tags_agent(kb, monkeypatch):
    # stub skill_manager 的 reference 接口，避免依赖真实安装
    import skill_manager as sm
    monkeypatch.setattr(sm, "list_skill_references", lambda sid: ["a.md", "b.md"])
    monkeypatch.setattr(sm, "load_skill_reference",
                        lambda sid, ref, agent_id=None: f"{sid} 的 {ref} 内容")
    r = kb.ingest_skill_references("minglijushi", "yiyi")
    assert r["ok"] and r["ingested"] == 2
    # 灌入的 reference 文档只对晞可见
    yiyi = {d["doc_id"] for d in kb.list_docs("yiyi", include_shared=False)}
    assert "skillref:minglijushi:a.md" in yiyi
    assert "skillref:minglijushi:b.md" in yiyi
    # 陶朱看不到
    ty = {d["doc_id"] for d in kb.list_docs("tianyuan", include_shared=False)}
    assert not any(x.startswith("skillref:minglijushi") for x in ty)
    # 幂等：再次灌库不重复
    r2 = kb.ingest_skill_references("minglijushi", "yiyi")
    assert r2["ingested"] == 0
