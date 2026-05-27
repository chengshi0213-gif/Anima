#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库 — 本地 RAG 核心
文档入库 → 分块 → Embedding（Qwen text-embedding-v3）→ 余弦检索
存储：~/.anima/data/kb/
"""
import json
import math
import re
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from openai import OpenAI

from config import QWEN_KEY, DATA_DIR

# ── 存储路径 ──────────────────────────────────────────
KB_DIR       = DATA_DIR / "kb"
INDEX_FILE   = KB_DIR / "index.json"
VECTORS_FILE = KB_DIR / "vectors.npz"
KB_DIR.mkdir(parents=True, exist_ok=True)

# ── Embedding 客户端（Qwen text-embedding-v3，支持中英文）──
_EMBED_CLIENT = OpenAI(
    api_key=QWEN_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
EMBED_MODEL   = "text-embedding-v3"
EMBED_DIM     = 1024   # text-embedding-v3 默认维度
CHUNK_SIZE    = 500    # 每块最大字符数
CHUNK_OVERLAP = 80     # 相邻块重叠字符数


# ══════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════

def _chunk_text(text: str) -> list[str]:
    """按段落分块，超长段落再切分。"""
    # 按双换行 / 标题符分段
    paragraphs = re.split(r'\n{2,}|(?<=[。！？\.\!\?])\n', text.strip())
    chunks, buf = [], ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) <= CHUNK_SIZE:
            buf = (buf + "\n" + para).strip()
        else:
            if buf:
                chunks.append(buf)
            # 段落本身过长：滑动切分
            if len(para) > CHUNK_SIZE:
                for i in range(0, len(para), CHUNK_SIZE - CHUNK_OVERLAP):
                    piece = para[i:i + CHUNK_SIZE]
                    if piece.strip():
                        chunks.append(piece.strip())
                buf = ""
            else:
                buf = para
    if buf:
        chunks.append(buf)
    return chunks or [text[:CHUNK_SIZE]]


def _embed(texts: list[str]) -> np.ndarray:
    """调用 Qwen Embedding API，返回 (N, DIM) float32 数组。"""
    # 批量最多 25 条，超过分批
    all_vecs = []
    batch = 25
    for i in range(0, len(texts), batch):
        resp = _EMBED_CLIENT.embeddings.create(
            model=EMBED_MODEL,
            input=texts[i:i + batch],
        )
        vecs = [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]
        all_vecs.extend(vecs)
    return np.array(all_vecs, dtype=np.float32)


def _cosine_sim(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """query_vec: (D,)，matrix: (N, D) → scores: (N,)"""
    q = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
    normed = matrix / norms
    return normed @ q


# ══════════════════════════════════════════════════════
#  KnowledgeBase 主类
# ══════════════════════════════════════════════════════

class KnowledgeBase:
    """线程不安全；aiohttp 里用 asyncio.to_thread 调用。"""

    def __init__(self):
        self._index: list[dict[str, Any]] = []   # chunk 元数据列表
        self._matrix: np.ndarray | None   = None  # (N, DIM)
        self._load()

    # ── 持久化 ──────────────────────────────────────
    def _load(self):
        if INDEX_FILE.exists():
            self._index = json.loads(INDEX_FILE.read_text("utf-8"))
        else:
            self._index = []
        if VECTORS_FILE.exists() and self._index:
            data = np.load(str(VECTORS_FILE))
            self._matrix = data["vectors"]
        else:
            self._matrix = np.empty((0, EMBED_DIM), dtype=np.float32)

    def _save(self):
        INDEX_FILE.write_text(json.dumps(self._index, ensure_ascii=False, indent=2), "utf-8")
        np.savez_compressed(str(VECTORS_FILE), vectors=self._matrix)

    # ── 入库 ────────────────────────────────────────
    def ingest(self, text: str, source_name: str, doc_id: str | None = None) -> dict:
        """
        将文本分块、嵌入后存入索引。
        返回 {"doc_id": ..., "chunks": N, "source": ...}
        """
        doc_id = doc_id or str(uuid.uuid4())[:8]
        chunks = _chunk_text(text)
        if not chunks:
            return {"error": "文本为空，无法入库"}

        vecs = _embed(chunks)    # (N, DIM)

        for i, (chunk, vec) in enumerate(zip(chunks, vecs)):
            self._index.append({
                "doc_id":  doc_id,
                "source":  source_name,
                "chunk_i": i,
                "text":    chunk,
            })
        # 追加到矩阵
        if self._matrix is None or self._matrix.shape[0] == 0:
            self._matrix = vecs
        else:
            self._matrix = np.vstack([self._matrix, vecs])

        self._save()
        return {"doc_id": doc_id, "source": source_name, "chunks": len(chunks)}

    # ── 检索 ────────────────────────────────────────
    def search(self, query: str, top_k: int = 5, doc_id: str | None = None) -> list[dict]:
        """
        语义检索，返回 top_k 个相关块。
        doc_id: 限定只在某个文档内检索（可选）。
        """
        if not self._index or self._matrix is None or self._matrix.shape[0] == 0:
            return []

        q_vec = _embed([query])[0]     # (DIM,)
        scores = _cosine_sim(q_vec, self._matrix)  # (N,)

        # 过滤文档
        indices = list(range(len(self._index)))
        if doc_id:
            indices = [i for i in indices if self._index[i]["doc_id"] == doc_id]

        # 排序
        ranked = sorted(indices, key=lambda i: scores[i], reverse=True)[:top_k]
        return [
            {
                "score":   float(scores[i]),
                "text":    self._index[i]["text"],
                "source":  self._index[i]["source"],
                "doc_id":  self._index[i]["doc_id"],
                "chunk_i": self._index[i]["chunk_i"],
            }
            for i in ranked
        ]

    # ── 文档列表 ─────────────────────────────────────
    def list_docs(self) -> list[dict]:
        """返回每个 doc 的摘要（不含 chunk 文本）。"""
        seen, docs = set(), []
        for item in self._index:
            did = item["doc_id"]
            if did not in seen:
                seen.add(did)
                count = sum(1 for x in self._index if x["doc_id"] == did)
                docs.append({
                    "doc_id": did,
                    "source": item["source"],
                    "chunks": count,
                })
        return docs

    # ── 删除 ────────────────────────────────────────
    def delete(self, doc_id: str) -> dict:
        before = len(self._index)
        keep = [i for i, x in enumerate(self._index) if x["doc_id"] != doc_id]
        if len(keep) == before:
            return {"error": f"文档 {doc_id} 不存在"}

        self._index   = [self._index[i] for i in keep]
        self._matrix  = self._matrix[keep] if keep else np.empty((0, EMBED_DIM), dtype=np.float32)
        self._save()
        return {"deleted": doc_id, "remaining": len(self._index)}

    # ── 上下文构建（供 Agent 调用）─────────────────────
    def build_context(self, query: str, top_k: int = 4) -> str:
        """返回格式化的检索上下文字符串，注入 system prompt。"""
        hits = self.search(query, top_k=top_k)
        if not hits:
            return ""
        lines = ["【知识库检索结果】"]
        for i, h in enumerate(hits, 1):
            lines.append(f"[{i}] 来源：{h['source']}（相关度 {h['score']:.2f}）")
            lines.append(h["text"])
            lines.append("")
        return "\n".join(lines)


# 单例（由 websocket_server 持有）
kb = KnowledgeBase()
