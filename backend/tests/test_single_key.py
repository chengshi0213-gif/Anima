#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_single_key.py — 单 API key 即可驱动全部人格/模型。

验证 first_available_model 与 _resolve_model 的兜底：
  - 只配一个 provider → 任何模型/agent 都落到该 provider。
  - 选了未配 provider 的模型 → 回退到已配 provider。
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import agent_base as ab  # noqa: E402


@pytest.fixture
def only_kimi(monkeypatch):
    # 只配 Kimi，其余清空
    monkeypatch.setattr(ab, "DEEPSEEK_KEY", "", raising=False)
    monkeypatch.setattr(ab, "QWEN_KEY", "", raising=False)
    monkeypatch.setattr(ab, "OPENROUTER_KEY", "", raising=False)
    monkeypatch.setattr(ab, "KIMI_KEY", "kk-test", raising=False)
    yield


def _mk_agent(api_key="", model="deepseek-chat", base_url=ab._DS):
    return ab.AgentBase(
        name="t", api_key=api_key, model=model, base_url=base_url,
        system_prompt="", tool_defs=[], tool_dispatch={},
    )


def test_first_available_picks_configured(only_kimi):
    k, url, mid = ab.first_available_model()
    assert k == "kk-test" and url == ab._KIMI and mid == "kimi-k2.5"


def test_first_available_none(monkeypatch):
    for v in ("DEEPSEEK_KEY", "KIMI_KEY", "QWEN_KEY", "OPENROUTER_KEY"):
        monkeypatch.setattr(ab, v, "", raising=False)
    assert ab.first_available_model() == ("", "", "")


def test_agent_default_provider_unset_falls_back(only_kimi):
    # agent 默认 DeepSeek 但没配 → 落到 Kimi
    a = _mk_agent(api_key="", model="deepseek-chat", base_url=ab._DS)
    k, url, mid = a._resolve_model(None)
    assert k == "kk-test" and url == ab._KIMI


def test_selected_model_unset_provider_falls_back(only_kimi):
    # 选了 Qwen 模型但没配 QWEN → 落到 Kimi
    a = _mk_agent(api_key="", model="deepseek-chat", base_url=ab._DS)
    k, url, mid = a._resolve_model("Qwen3.7-Max")
    assert k == "kk-test" and url == ab._KIMI


def test_configured_provider_keeps_its_model(only_kimi):
    # 选 Kimi 模型 + 已配 → 用 Kimi 自己的
    a = _mk_agent(api_key="kk-test", model="kimi-k2.6", base_url=ab._KIMI)
    k, url, mid = a._resolve_model("Kimi-K2.6")
    assert k == "kk-test" and url == ab._KIMI and mid == "kimi-k2.6"


def test_deepseek_only_powers_qwen_agent(monkeypatch):
    monkeypatch.setattr(ab, "DEEPSEEK_KEY", "ds-test", raising=False)
    monkeypatch.setattr(ab, "KIMI_KEY", "", raising=False)
    monkeypatch.setattr(ab, "QWEN_KEY", "", raising=False)
    monkeypatch.setattr(ab, "OPENROUTER_KEY", "", raising=False)
    a = _mk_agent(api_key="", model="qwen3.7-max", base_url=ab._QWEN)
    k, url, mid = a._resolve_model("Qwen3.7-Max")
    assert k == "ds-test" and url == ab._DS and mid == "deepseek-chat"
