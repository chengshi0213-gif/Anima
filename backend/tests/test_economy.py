#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_economy.py — 成就 + 灵犀经济 单测（纯逻辑，临时文件）。"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import economy as ec  # noqa: E402


@pytest.fixture
def iso(tmp_path, monkeypatch):
    monkeypatch.setattr(ec, "_PATH", tmp_path / "economy.json")
    yield


def test_status_progress_and_done(iso):
    s = ec.status({"messages": 100})
    by = {a["id"]: a for a in s["achievements"]}
    assert by["first_words"]["done"] is True
    assert by["hundred"]["done"] is True
    assert "all_four" not in by   # 人格合并后此成就已移除
    assert s["summary"]["claimable"] >= 20 + 60


def test_claim_awards_and_no_double(iso):
    sig = {"messages": 1}
    r1 = ec.claim("first_words", sig)
    assert r1["ok"] and r1["reward"] == 20 and r1["lingxi"] == 20
    r2 = ec.claim("first_words", sig)
    assert not r2["ok"] and r2["lingxi"] == 20          # 不可重复领
    assert ec.balance() == 20


def test_claim_not_done(iso):
    r = ec.claim("thousand", {"messages": 5})
    assert not r["ok"]


def test_spend(iso):
    ec.claim("hundred", {"messages": 100})              # +60
    assert ec.balance() == 60
    r = ec.spend(50, "skin:yiyi_starfall")
    assert r["ok"] and r["lingxi"] == 10 and "skin:yiyi_starfall" in r["unlocks"]
    r2 = ec.spend(50, "skin:other")
    assert not r2["ok"]                                 # 灵犀不足
    r3 = ec.spend(10, "skin:yiyi_starfall")
    assert not r3["ok"]                                 # 已解锁


def test_legend_achievement(iso):
    s = ec.status({"legend_skills": 1})
    by = {a["id"]: a for a in s["achievements"]}
    assert by["skill_legend"]["done"] and by["skill_legend"]["tier"] == "legend"


def test_grant_idempotent(iso):
    r1 = ec.grant(20, "invite_activated", "使用结缘码")
    assert r1["ok"] and r1["granted"] == 20 and r1["lingxi"] == 20
    r2 = ec.grant(20, "invite_activated", "使用结缘码")     # 同 key 不重复
    assert not r2["ok"] and r2["reason"] == "already_granted" and r2["lingxi"] == 20
    assert ec.balance() == 20
    assert "invite_activated" in ec.grants()


def test_grant_invalid(iso):
    assert not ec.grant(0, "k")["ok"]                       # 金额无效
    assert not ec.grant(10, "")["ok"]                       # 无 key
    assert ec.balance() == 0


def test_grant_multiple_keys(iso):
    for i in range(1, 4):
        assert ec.grant(30, f"invite_reward_{i}", f"第{i}位")["ok"]
    assert ec.balance() == 90                               # 邀请封顶3次 = 90
