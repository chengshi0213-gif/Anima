#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_memory_embed.py — 本地语义向量编码（M4）单元测试

验证 memory_embed 在缺少模型文件时优雅降级：
  - is_available() 返回 False
  - embed_texts() 返回 None（不抛异常）
  - cosine_sim() 数学计算正确

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_memory_embed.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import memory_embed as me  # noqa: E402


@pytest.fixture(autouse=True)
def reset_embed_state():
    me.reset()
    yield
    me.reset()


def test_unavailable_without_model_files():
    # 测试环境未放置 model.onnx / tokenizer.json，应判定为不可用
    assert me.is_available() is False


def test_embed_texts_returns_none_when_unavailable():
    assert me.embed_texts(["随便一句话"]) is None


def test_embed_texts_empty_input_returns_empty_array():
    out = me.embed_texts([])
    assert out is not None
    assert out.shape == (0, me.EMBED_DIM)


def test_cosine_sim_basic():
    matrix = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)
    q = np.array([1.0, 0.0], dtype=np.float32)
    scores = me.cosine_sim(q, matrix)
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.0)
    assert scores[2] == pytest.approx(1.0 / np.sqrt(2))


def test_cosine_sim_empty_matrix():
    matrix = np.empty((0, 2), dtype=np.float32)
    q = np.array([1.0, 0.0], dtype=np.float32)
    scores = me.cosine_sim(q, matrix)
    assert scores.shape == (0,)
