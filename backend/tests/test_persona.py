#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_persona.py — 人格卡框架（M2）单元测试 (pytest)

锁定：
  - 四个核心人格卡齐全、按序、字段完整；
  - compose_base_prompt 正确填充用户称谓占位符（无残留 {…}）；
  - 公开卡片不泄露完整 base_prompt 正文；
  - 人格卡的 name/voice 与 routes/config 的默认值一致（防止两处漂移）；
  - worker 的 system_prompt 确实来自人格卡（行为不变）。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_persona.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import persona  # noqa: E402


def test_core_personas_present_and_ordered():
    assert persona.CORE_PERSONA_IDS == ["xi"]
    cards = persona.list_personas()
    assert [c["id"] for c in cards] == ["xi"]


def test_public_card_fields_and_no_prompt_leak():
    for c in persona.list_personas():
        for k in ("id", "name", "tagline", "role", "element",
                  "color", "summary", "voice", "model", "capabilities"):
            assert k in c, f"{c['id']} 缺字段 {k}"
        assert isinstance(c["capabilities"], list) and c["capabilities"]
        # 公开卡片不应包含完整 prompt 正文
        assert "base_prompt" not in c


def test_compose_fills_address_no_leftover_placeholder():
    for pid in persona.CORE_PERSONA_IDS:
        prompt = persona.compose_base_prompt(pid)
        assert prompt, f"{pid} 底色为空"
        # 占位符必须全部被替换
        assert "{user_name}" not in prompt
        assert "{investor}" not in prompt


def test_address_key_matches_placeholder():
    # 每张卡的 base_prompt 模板必须含其 address_key 对应的占位符
    for pid, card in persona.PERSONAS.items():
        assert "{" + card.address_key + "}" in card.base_prompt


def test_unknown_persona():
    assert persona.get_persona("nope") is None
    assert persona.compose_base_prompt("nope") == ""


def test_name_voice_no_drift_with_routes_config():
    # 核心人格卡的显示名/音色必须与 routes/config 的默认表一致
    from routes.config import DEFAULT_AGENT_NAMES, AGENT_VOICES
    for pid in persona.CORE_PERSONA_IDS:
        card = persona.PERSONAS[pid]
        assert DEFAULT_AGENT_NAMES[pid] == card.name
        assert AGENT_VOICES[pid] == card.voice


def test_shoucang_voice_polish_present():
    """M7：守藏的谏臣风骨语气层 + 文言强度校准必须在底色里（防打磨被改没）。"""
    p = persona.compose_base_prompt("shoucang")
    # 谏臣腔调标志
    assert "谏臣" in p
    for trait in ("立常理", "借古喻今", "反问进谏", "辩证", "恭敬而不退"):
        assert trait in p, f"守藏语气特征缺失: {trait}"
    # 文言强度校准：平时偏白、进谏拉满（两端都要写明，避免用力过猛）
    assert "七分白" in p
    assert "进谏" in p and "拉满" in p
    # 进谏范例骨架在场（供模型 few-shot）
    assert "狸奴" in p or "鼎" in p
    # 职能层未被打磨覆盖掉
    assert "知识守护者" in p and "成长" in p


def test_shoucang_voice_only_persona_with_remonstrance():
    """谏臣腔调是守藏专属，不应渗进 Anima。"""
    p = persona.compose_base_prompt("xi")
    assert "谏臣" not in p, "xi 不应带守藏的谏臣腔调"


def test_workers_consume_persona():
    # Anima（xi）动态拼接，底色须作为前缀出现
    from xi_worker import XiWorker
    w = XiWorker()
    s = w._compose_system()
    assert s.startswith(persona.compose_base_prompt("xi"))


def test_xi_memory_confirmation_demo_present():
    """M1：「记下了」是记忆写入确认的口头禅，需有示范对话支撑（避免名实不符）。"""
    p = persona.compose_base_prompt("xi")
    assert "记下了" in p
    assert "[用：记一下" in p
