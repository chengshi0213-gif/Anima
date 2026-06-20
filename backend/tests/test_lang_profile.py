#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_lang_profile.py — 用户语言图谱单元测试

覆盖：
  - 原有特征提取（句长/口头禅/语气词/标点/省略号）
  - G1 新增特征：emoji 率 / 长度分布 / 英文夹杂率
  - get_profile_block 包含三成原则 + 禁区清单
  - save_llm_advice 写入后出现在 profile block
  - record_message + 自动分析触发
  - 每周语体复盘 cron 可被调度器解析
  - run_weekly_lang_review 数据不足时 skip

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_lang_profile.py -v
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import lang_profile as lp  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_profile(tmp_path, monkeypatch):
    test_path = tmp_path / "lang_profile.json"
    monkeypatch.setattr(lp, "_PATH", test_path)
    yield test_path


# ── 特征提取：原有 + G1 新增 ────────────────────────────────────

def _make_buffer(msgs: list[str]) -> dict:
    feat = lp._analyze(msgs)
    return feat


def test_analyze_basic_features():
    msgs = ["嗯嗯好的", "就是感觉有点累", "反正先这样吧", "然后呢",
            "其实我觉得还行啊", "就是说嘛", "那个什么来着",
            "哈哈笑死了", "感觉不错哦", "算了不想了吧"]
    feat = _make_buffer(msgs)
    assert feat["style"] in ("short", "medium")
    assert "avg_len" in feat
    assert isinstance(feat["top_fillers"], list)
    assert isinstance(feat["top_endings"], list)


def test_analyze_emoji_rate():
    msgs_with_emoji = [
        "今天心情不错😊", "好的👌", "哈哈🤣太搞笑了",
        "没有emoji的消息", "也没有这条",
        "这条有🎉", "还有这个💪好吧",
        "普通消息一条", "又一条普通的", "最后一条🎶",
    ]
    feat = _make_buffer(msgs_with_emoji)
    assert "emoji_rate" in feat
    assert feat["emoji_rate"] >= 0.5

    msgs_no_emoji = ["你好啊", "今天怎么样", "还行吧", "嗯嗯好的", "那就这样"]
    feat2 = _make_buffer(msgs_no_emoji)
    assert feat2["emoji_rate"] == 0


def test_analyze_length_distribution():
    short_msgs = ["嗯", "好", "行吧", "知道了", "ok",
                  "嗯嗯", "好的", "行", "对", "哦"]
    feat = _make_buffer(short_msgs)
    ld = feat["len_distribution"]
    assert ld["short_pct"] >= 0.8


def test_analyze_en_mix_rate():
    mixed_msgs = [
        "这个 feature 不错", "我觉得 ok", "用 Python 写吧",
        "纯中文消息", "也是纯中文",
        "deploy 一下", "check 一下 status",
        "这条没有英文", "这条也没有", "最后 review 一下",
    ]
    feat = _make_buffer(mixed_msgs)
    assert feat["en_mix_rate"] >= 0.5

    cn_msgs = ["纯中文消息一", "纯中文消息二", "纯中文消息三",
               "纯中文消息四", "纯中文消息五"]
    feat2 = _make_buffer(cn_msgs)
    assert feat2["en_mix_rate"] == 0


# ── get_profile_block：三成原则 + 禁区 ──────────────────────────

def test_profile_block_contains_principles(isolate_profile):
    msgs = ["嗯嗯好的啊", "就是感觉有点累", "反正先这样吧啊", "然后呢",
            "其实我觉得还行", "就是说嘛", "那个什么来着哦",
            "哈哈笑死了", "感觉不错", "算了不想了"]
    for m in msgs:
        lp.record_message(m)

    block = lp.get_profile_block()
    assert "三成原则" in block
    assert "禁区" in block
    assert "脏话不跟" in block
    assert "火星文不跟" in block
    assert "标点纪律不破" in block


def test_profile_block_empty_when_insufficient():
    block = lp.get_profile_block()
    assert block == ""


def test_profile_block_reports_emoji_habit(isolate_profile):
    msgs = [f"消息{i}😊好的" for i in range(10)]
    for m in msgs:
        lp.record_message(m)
    block = lp.get_profile_block()
    assert "emoji" in block


def test_profile_block_reports_en_mix(isolate_profile):
    msgs = [f"这个 feature{i} 不错吧" for i in range(10)]
    for m in msgs:
        lp.record_message(m)
    block = lp.get_profile_block()
    assert "英文" in block


# ── save_llm_advice ─────────────────────────────────────────────

def test_save_llm_advice_appears_in_block(isolate_profile):
    msgs = ["嗯嗯好的啊", "就是感觉有点累", "反正先这样吧啊", "然后呢",
            "其实我觉得还行", "就是说嘛", "那个什么来着哦",
            "哈哈笑死了", "感觉不错", "算了不想了"]
    for m in msgs:
        lp.record_message(m)

    lp.save_llm_advice("你可以适度缩短句子长度，偶尔用一个语气词收尾。")
    block = lp.get_profile_block()
    assert "本周语体微调建议" in block
    assert "适度缩短句子长度" in block


def test_save_llm_advice_in_status(isolate_profile):
    lp.save_llm_advice("测试建议")
    status = lp.get_status()
    assert status["llm_advice"] == "测试建议"
    assert status["advice_updated"] is not None


# ── record_message 触发分析 ─────────────────────────────────────

def test_record_message_triggers_analysis(isolate_profile):
    for i in range(lp.UPDATE_EVERY):
        lp.record_message(f"这是第{i}条测试消息内容")
    status = lp.get_status()
    assert status["message_count"] == lp.UPDATE_EVERY
    assert status["features"] != {}
    assert "emoji_rate" in status["features"]
    assert "len_distribution" in status["features"]
    assert "en_mix_rate" in status["features"]


# ── 每周语体复盘 cron 可被调度器解析 ──────────────────────────

def test_weekly_lang_cron_is_valid():
    import scholar_worker as sw
    from scheduler import TaskScheduler
    trigger = TaskScheduler._make_trigger("cron", sw.WEEKLY_LANG_CRON)
    assert trigger is not None


# ── run_weekly_lang_review 数据不足时 skip ──────────────────────

def test_weekly_lang_review_skips_when_insufficient(isolate_profile):
    import scholar_worker as sw
    worker = sw.ShoucangWorker()
    result = worker.run_weekly_lang_review()
    assert result["status"] == "skipped"
