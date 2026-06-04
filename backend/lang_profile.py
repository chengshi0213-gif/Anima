#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lang_profile.py — 用户语言图谱

随对话积累用户的语言形式特征（口头禅、句子节奏、语气词、标点习惯），
供 Anima 在风格上逐渐向用户靠近——形式接近，判断是她的。

存储：~/.anima/data/lang_profile.json
更新：每 UPDATE_EVERY 条用户消息触发一次轻量分析（纯 Python，不调模型）
注入：get_profile_block() 返回紧凑的风格提示，追加到 system prompt 末尾
     数据不足（< UPDATE_EVERY 条）时返回空串，不乱猜。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from config import DATA_DIR
    _PATH = DATA_DIR / "lang_profile.json"
except Exception:
    _PATH = Path.home() / ".anima" / "data" / "lang_profile.json"

# ── 参数 ──────────────────────────────────────────────────────────
UPDATE_EVERY = 10    # 每积累 N 条消息重新分析一次
BUFFER_MAX   = 120   # 滚动缓冲最多保留 N 条（取近期样本）

# 识别口头禅的候选词（频次 ≥ 2 才入选）
_FILLERS = [
    "就是", "反正", "其实", "说白了", "也就是", "就是说",
    "说实话", "感觉", "然后", "不过", "但是", "emmm", "额",
    "嗯嗯", "那个", "这个", "啊对", "对对", "还好", "还行",
    "哈哈", "哈哈哈", "笑死", "蚌埠住了",
]
# 常见句尾语气词
_ENDINGS  = list("了啊吗呢嘛哦呀哈嗯吧")
# 标点字符集
_PUNCT    = set("，。！？；：")


# ── 持久化 ────────────────────────────────────────────────────────

def _load() -> dict:
    if _PATH.exists():
        try:
            return json.loads(_PATH.read_text("utf-8"))
        except Exception:
            pass
    return {"message_count": 0, "last_updated": None, "buffer": [], "features": {}}


def _save(data: dict) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


# ── 分析核心（纯 Python，不调模型）─────────────────────────────────

def _analyze(buffer: list[str]) -> dict:
    msgs = [m.strip() for m in buffer if m and len(m.strip()) > 1]
    if len(msgs) < 5:
        return {}

    # 平均句长 → 节奏风格
    avg_len = sum(len(m) for m in msgs) / len(msgs)
    if avg_len < 12:
        style = "short"
    elif avg_len < 35:
        style = "medium"
    else:
        style = "long"

    # 句尾语气词 top 3
    ending_count: dict[str, int] = {}
    for msg in msgs:
        last = msg[-1] if msg else ""
        if last in _ENDINGS:
            ending_count[last] = ending_count.get(last, 0) + 1
    top_endings = [e for e, _ in
                   sorted(ending_count.items(), key=lambda x: -x[1])[:3]]

    # 口头禅 top 3（频次 ≥ 2）
    full = " ".join(msgs)
    filler_hits = {f: full.count(f) for f in _FILLERS if full.count(f) >= 2}
    top_fillers = [f for f, _ in
                   sorted(filler_hits.items(), key=lambda x: -x[1])[:3]]

    # 标点稀疏（< 35% 消息含标点）
    punct_rate = sum(1 for m in msgs if any(c in _PUNCT for c in m)) / len(msgs)
    punct_sparse = punct_rate < 0.35

    # 省略号习惯
    uses_ellipsis = any("..." in m or "…" in m for m in msgs)

    return {
        "style":        style,
        "avg_len":      round(avg_len, 1),
        "top_endings":  top_endings,
        "top_fillers":  top_fillers,
        "punct_sparse": punct_sparse,
        "uses_ellipsis": uses_ellipsis,
    }


# ── 公开接口 ──────────────────────────────────────────────────────

def record_message(text: str) -> None:
    """记录一条用户消息；每 UPDATE_EVERY 条触发重新分析。容错，不抛。"""
    try:
        text = (text or "").strip()
        if not text or len(text) < 2:
            return
        data = _load()
        buf: list[str] = data.get("buffer", [])
        buf.append(text)
        if len(buf) > BUFFER_MAX:
            buf = buf[-BUFFER_MAX:]
        data["buffer"] = buf
        data["message_count"] = data.get("message_count", 0) + 1
        if data["message_count"] % UPDATE_EVERY == 0:
            data["features"] = _analyze(buf)
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
        _save(data)
    except Exception:
        pass


def get_profile_block() -> str:
    """
    返回注入到 system prompt 的语言图谱块。
    数据不足（< UPDATE_EVERY 条）时返回空串，不乱猜。
    """
    try:
        data = _load()
        count = data.get("message_count", 0)
        feat  = data.get("features", {})
        if not feat or count < UPDATE_EVERY:
            return ""

        lines: list[str] = []

        style = feat.get("style", "")
        if style == "short":
            lines.append("句子偏短，简洁直接")
        elif style == "long":
            lines.append("习惯一口气说长句")

        fillers = feat.get("top_fillers", [])
        if fillers:
            lines.append("口头禅：" + "、".join(fillers))

        endings = feat.get("top_endings", [])
        if endings:
            lines.append("句尾惯用：" + "".join(endings))

        if feat.get("punct_sparse"):
            lines.append("不太打标点")

        if feat.get("uses_ellipsis"):
            lines.append("喜欢用省略号")

        if not lines:
            return ""

        summary = "，".join(lines) + "。"
        return (
            "\n\n## 他说话的样子（" + str(count) + " 条消息后积累）\n"
            + summary + "\n"
            + "风格上你可以向他靠近，但判断是你的。"
        )
    except Exception:
        return ""


def get_status() -> dict:
    """调试 / 设置页查看图谱状态。"""
    try:
        data = _load()
        return {
            "message_count": data.get("message_count", 0),
            "last_updated":  data.get("last_updated"),
            "features":      data.get("features", {}),
            "buffer_size":   len(data.get("buffer", [])),
        }
    except Exception:
        return {}


def reset() -> None:
    """清空语言图谱（设置页用）。"""
    _save({"message_count": 0, "last_updated": None, "buffer": [], "features": {}})
