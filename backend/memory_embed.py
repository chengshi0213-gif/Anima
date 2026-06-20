#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_embed.py — 本地语义向量编码（M4）

纯本地 bge-small-zh-v1.5（ONNX）编码记忆文本，守"绝不联网"。
模型文件需放到 MODEL_DIR 下（model.onnx + tokenizer.json，用户自行下载，
两个文件均不存在或 onnxruntime/tokenizers 未安装时 is_available() 返回
False，memory_sqlite.search() 自动降级回纯 FTS5，不报错。
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from config import DATA_DIR

MODEL_DIR = DATA_DIR / "models" / "bge-small-zh-v1.5"
EMBED_DIM = 512                  # bge-small-zh-v1.5 输出维度（仅供参考）
MAX_SEQ_LEN = 512
VECTOR_SIM_THRESHOLD = 0.35      # 余弦相似度低于此值的语义召回结果不返回

_session = None
_tokenizer = None
_unavailable = False


def _try_load() -> None:
    global _session, _tokenizer, _unavailable
    if _session is not None or _unavailable:
        return
    try:
        onnx_path = MODEL_DIR / "model.onnx"
        tok_path = MODEL_DIR / "tokenizer.json"
        if not onnx_path.exists() or not tok_path.exists():
            _unavailable = True
            return
        import onnxruntime as ort
        from tokenizers import Tokenizer
        _session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        _tokenizer = Tokenizer.from_file(str(tok_path))
    except Exception:
        _unavailable = True


def is_available() -> bool:
    """本地 embedding 模型是否就绪（onnxruntime + 模型文件均存在）。"""
    _try_load()
    return _session is not None and _tokenizer is not None


def embed_texts(texts: list[str]) -> Optional[np.ndarray]:
    """编码一批文本为 (N, D) float32 单位向量；不可用时返回 None（调用方应降级）。"""
    if not texts:
        return np.empty((0, EMBED_DIM), dtype=np.float32)
    if not is_available():
        return None
    try:
        encodings = _tokenizer.encode_batch(texts)
        max_len = min(MAX_SEQ_LEN, max(len(e.ids) for e in encodings))
        input_ids, attn_mask, type_ids = [], [], []
        for e in encodings:
            ids = e.ids[:max_len]
            mask = e.attention_mask[:max_len]
            pad = max_len - len(ids)
            input_ids.append(ids + [0] * pad)
            attn_mask.append(mask + [0] * pad)
            type_ids.append([0] * max_len)

        feed: dict[str, np.ndarray] = {}
        names = {inp.name for inp in _session.get_inputs()}
        if "input_ids" in names:
            feed["input_ids"] = np.array(input_ids, dtype=np.int64)
        if "attention_mask" in names:
            feed["attention_mask"] = np.array(attn_mask, dtype=np.int64)
        if "token_type_ids" in names:
            feed["token_type_ids"] = np.array(type_ids, dtype=np.int64)

        outputs = _session.run(None, feed)
        last_hidden = outputs[0]            # (N, L, D)
        pooled = last_hidden[:, 0, :]       # CLS pooling（bge 官方推荐）
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return (pooled / np.clip(norms, 1e-9, None)).astype(np.float32)
    except Exception:
        return None


def cosine_sim(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """query_vec: (D,)，matrix: (N, D) → (N,) 余弦相似度。"""
    if matrix.shape[0] == 0:
        return np.empty((0,), dtype=np.float32)
    q_norm = np.linalg.norm(query_vec) + 1e-9
    m_norms = np.linalg.norm(matrix, axis=1) + 1e-9
    return (matrix @ query_vec) / (m_norms * q_norm)


def reset() -> None:
    """测试用：清空已加载状态，强制下次调用重新探测模型文件。"""
    global _session, _tokenizer, _unavailable
    _session, _tokenizer, _unavailable = None, None, False
