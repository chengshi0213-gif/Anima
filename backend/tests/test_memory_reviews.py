#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_memory_reviews.py — Phase3 子阶段：矛盾待确认队列单元测试

覆盖：
  - add_review：写入 / 对称去重（同对第二次 open 返回 None）
  - list_pending_reviews：只返回 open 项
  - resolve_review：关闭 + dismissed
  - find_review_candidates：相似不全等的出候选；纯重复 + 已 open 对跳过；
    A/D 类标 identity_conflict
  - format_pending_reviews：格式化块含关键字段
  - run_weekly_review_scan：候选为空时跳过（无需 LLM）

运行:
    cd E:\\AI\\workspace\\Anima\\backend
    python -m pytest tests/test_memory_reviews.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import memory_injector as mi
from memory_sqlite import SQLiteMemoryBackend
from scholar_worker import ShoucangWorker


@pytest.fixture(autouse=True)
def sqlite_mem(tmp_path, monkeypatch):
    backend = SQLiteMemoryBackend(tmp_path / "mem.db")
    monkeypatch.setattr(mi, "_backend", backend)
    mi.invalidate_cache()
    yield backend
    mi.invalidate_cache()


# ── add_review / list / resolve ─────────────────────────────────────────

def test_add_review_returns_id(sqlite_mem):
    rid = sqlite_mem.add_review("id_a", "id_b", "A", "identity_conflict", "城市矛盾")
    assert rid is not None and len(rid) > 0


def test_add_review_dedup_symmetric(sqlite_mem):
    sqlite_mem.add_review("id_a", "id_b", "B", "possible_contradiction", "偏好冲突")
    # 同对换顺序 → open 对已存在，返回 None
    assert sqlite_mem.add_review("id_b", "id_a", "B", "possible_contradiction", "反向") is None


def test_add_review_different_pairs_both_created(sqlite_mem):
    r1 = sqlite_mem.add_review("id_a", "id_b", "A", "identity_conflict", "矛盾1")
    r2 = sqlite_mem.add_review("id_a", "id_c", "A", "identity_conflict", "矛盾2")
    assert r1 is not None and r2 is not None and r1 != r2


def test_list_pending_reviews_only_open(sqlite_mem):
    rid = sqlite_mem.add_review("id_a", "id_b", "C", "possible_contradiction", "状态矛盾")
    sqlite_mem.add_review("id_c", "id_d", "B", "possible_contradiction", "偏好矛盾")
    # 关掉第一条
    sqlite_mem.resolve_review(rid, "用户说是上海")

    pending = sqlite_mem.list_pending_reviews()
    assert len(pending) == 1
    assert pending[0]["entry_id_a"] in ("id_c", "id_d")


def test_resolve_review_resolved(sqlite_mem):
    rid = sqlite_mem.add_review("x", "y", "A", "identity_conflict", "名字矛盾")
    ok = sqlite_mem.resolve_review(rid, "用户已确认是小明", status="resolved")
    assert ok is True
    # 不再出现在 pending
    assert all(r["id"] != rid for r in sqlite_mem.list_pending_reviews())


def test_resolve_review_dismissed(sqlite_mem):
    rid = sqlite_mem.add_review("x", "y", "B", "possible_contradiction", "细节")
    ok = sqlite_mem.resolve_review(rid, status="dismissed")
    assert ok is True
    assert all(r["id"] != rid for r in sqlite_mem.list_pending_reviews())


def test_resolve_review_idempotent_already_closed(sqlite_mem):
    rid = sqlite_mem.add_review("x", "y", "B", "possible_contradiction", "细节")
    sqlite_mem.resolve_review(rid, status="resolved")
    # 第二次关同一条 → 返回 False（rowcount=0）
    assert sqlite_mem.resolve_review(rid, status="resolved") is False


# ── find_review_candidates ──────────────────────────────────────────────

def test_find_candidates_detects_similar_pair(sqlite_mem):
    # 同分类下内容相似但不全等 → 应出候选
    sqlite_mem.write("城市A", "我在上海做电商", "B", "xi", 3)
    sqlite_mem.write("城市B", "我在上海做外贸电商", "B", "xi", 3)
    cands = sqlite_mem.find_review_candidates(sim_threshold=0.3)
    assert len(cands) >= 1
    assert cands[0]["category"] == "B"


def test_find_candidates_skips_exact_duplicates(sqlite_mem):
    # 纯重复交给 merge_near_duplicates，不应出候选
    sqlite_mem.write("k1", "我在做跨境电商", "C", "xi", 3)
    sqlite_mem.write("k2", "我在做跨境电商", "C", "xi", 3)
    cands = sqlite_mem.find_review_candidates()
    assert len(cands) == 0


def test_find_candidates_identity_conflict_for_AD(sqlite_mem):
    # A/D 类 → conflict_type 应是 identity_conflict
    sqlite_mem.write("名字A", "用户叫小明", "A", "xi", 4)
    sqlite_mem.write("名字B", "用户叫小亮", "A", "xi", 4)
    cands = sqlite_mem.find_review_candidates(sim_threshold=0.2)
    assert any(c["conflict_type"] == "identity_conflict" for c in cands)


def test_find_candidates_skips_already_open_pair(sqlite_mem):
    ea = sqlite_mem.write("k1", "用户在上海工作", "A", "xi", 4)
    eb = sqlite_mem.write("k2", "用户在北京工作", "A", "xi", 4)
    # 手动先 flag
    sqlite_mem.add_review(ea, eb, "A", "identity_conflict", "城市冲突")
    cands = sqlite_mem.find_review_candidates(sim_threshold=0.2)
    # 该对已有 open review，不应再出候选
    flagged = {(min(c["entry_id_a"], c["entry_id_b"]),
                max(c["entry_id_a"], c["entry_id_b"])) for c in cands}
    assert (min(ea, eb), max(ea, eb)) not in flagged


def test_find_candidates_no_cross_category(sqlite_mem):
    # 同 value 不同 category → 不合并，不出候选（前提：不同类不比较）
    sqlite_mem.write("k1", "我在做电商项目", "B", "xi", 3)
    sqlite_mem.write("k2", "我在做电商项目", "C", "xi", 3)
    cands = sqlite_mem.find_review_candidates()
    # 不同分类不在同一桶里比较
    assert len(cands) == 0


# ── format_pending_reviews surfacing ───────────────────────────────────

def test_format_pending_reviews_empty(sqlite_mem):
    from memory_injector import format_pending_reviews
    assert format_pending_reviews() == ""


def test_format_pending_reviews_has_content(sqlite_mem):
    from memory_injector import format_pending_reviews
    sqlite_mem.add_review("id_a", "id_b", "A", "identity_conflict", "城市：上海 vs 北京")
    block = format_pending_reviews()
    assert "确认" in block          # 含"有几件事想找你确认"
    assert "城市" in block
    assert "review_id" in block
    assert "身份/关系" in block      # identity_conflict 标签


def test_format_pending_reviews_max_items(sqlite_mem):
    from memory_injector import format_pending_reviews
    for i in range(5):
        sqlite_mem.add_review(f"a{i}", f"b{i}", "B", "possible_contradiction", f"矛盾{i}")
    block = format_pending_reviews(max_items=2)
    # 每条 entry 里有一个 review_id: <uuid>，用破折号计行数更稳
    entry_lines = [ln for ln in block.splitlines() if ln.strip().startswith("-")]
    assert len(entry_lines) == 2


# ── run_weekly_review_scan 无候选时跳过 ────────────────────────────────

def test_weekly_review_scan_skips_when_no_candidates(sqlite_mem):
    # 无记忆 → 无候选 → status=skipped，不调 LLM
    worker = ShoucangWorker()
    result = worker.run_weekly_review_scan()
    assert result["status"] == "skipped"
