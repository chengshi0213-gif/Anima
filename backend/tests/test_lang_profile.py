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


# ── Phase4：从真实语料发现口头禅/起头（不止固定表）────────────────

def test_discover_phrases_finds_recurring_custom_phrase():
    # "我寻思" 不在 _FILLERS 固定表里，但跨多条复现 → 应被发现
    msgs = [
        "我寻思这个方案能行", "我寻思要不再等等", "我寻思你说得对",
        "我寻思明天再弄", "我寻思这事儿没那么急",
        "今天天气不错呀", "晚点再说吧", "好的没问题",
        "那就这样定了", "随便你怎么弄", "都可以的啦", "嗯行吧",
    ]
    discovered = lp._discover_phrases(msgs)
    assert "我寻思" in discovered
    # 长短语优先去子串：不应同时报出它的子串
    assert "我寻" not in discovered and "寻思" not in discovered


def test_discover_phrases_excludes_fixed_table_words():
    # "就是" 在 _FILLERS 固定表里 → 发现列表里不重复报
    msgs = [f"就是觉得这样挺好的{i}" for i in range(12)]
    discovered = lp._discover_phrases(msgs)
    assert "就是" not in discovered


def test_discover_phrases_respects_doc_frequency_floor():
    # 只在 2 条里出现的短语，达不到 min_docs(=3) → 不算口头禅
    msgs = ["蓝瘦香菇啊", "蓝瘦香菇呀"] + [f"普通消息{i}内容" for i in range(10)]
    discovered = lp._discover_phrases(msgs)
    assert "蓝瘦香" not in discovered and "蓝瘦香菇" not in discovered


def test_discover_openers_finds_habitual_opening():
    msgs = [
        "我寻思这个能行", "我寻思要不等等", "我寻思你对",
        "我寻思先放着", "我寻思别急",
        "今天还行", "晚点说", "好的", "那就这样", "随便", "都行", "嗯",
    ]
    openers = lp._discover_openers(msgs)
    assert any(o.startswith("我寻") for o in openers)


def test_analyze_exposes_discovered_and_openers():
    msgs = [
        "我寻思这个方案能行", "我寻思要不再等等", "我寻思你说得对",
        "我寻思明天再弄", "我寻思这事儿没那么急",
        "今天天气不错呀", "晚点再说吧", "好的没问题",
        "那就这样定了", "随便你怎么弄",
    ]
    feat = lp._analyze(msgs)
    assert "discovered_fillers" in feat and "openers" in feat
    assert "我寻思" in feat["discovered_fillers"]


def test_profile_block_surfaces_discovered_phrase(isolate_profile):
    msgs = [
        "我寻思这个方案能行", "我寻思要不再等等", "我寻思你说得对",
        "我寻思明天再弄", "我寻思这事儿没那么急",
        "今天天气不错呀", "晚点再说吧", "好的没问题",
        "那就这样定了", "随便你怎么弄",
    ]
    for m in msgs:
        lp.record_message(m)
    block = lp.get_profile_block()
    assert "口头禅" in block
    assert "我寻思" in block


# ── Phase4：语义纹理层 ──────────────────────────────────────────

def test_parse_review_output_splits_two_blocks():
    raw = (
        "【微调建议】\n你可以适度缩短句子。\n适度少用感叹号。\n"
        "【表达习惯】\n他习惯先抛结论再解释。\n爱用反问表达不满。"
    )
    advice, texture = lp.parse_review_output(raw)
    assert "适度缩短句子" in advice
    assert "先抛结论" in texture
    assert "微调建议" not in advice  # 标题不该混进正文


def test_parse_review_output_fallback_no_markers():
    raw = "你可以适度精简。"
    advice, texture = lp.parse_review_output(raw)
    assert advice == "你可以适度精简。"
    assert texture == ""


def test_save_texture_appears_in_block_and_status(isolate_profile):
    msgs = ["嗯嗯好的啊", "就是感觉有点累", "反正先这样吧啊", "然后呢",
            "其实我觉得还行", "就是说嘛", "那个什么来着哦",
            "哈哈笑死了", "感觉不错", "算了不想了"]
    for m in msgs:
        lp.record_message(m)

    lp.save_texture("他习惯先抛结论再解释，爱举具体例子。")
    block = lp.get_profile_block()
    assert "他表达的习惯" in block
    assert "先抛结论再解释" in block
    assert "三成原则照旧" in block  # 守住底色的提醒还在

    status = lp.get_status()
    assert "先抛结论" in status["texture"]
    assert status["texture_updated"] is not None
