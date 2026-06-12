#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lang_profile.py — 用户语言图谱

随对话积累用户的语言形式特征（口头禅、句子节奏、语气词、标点习惯、emoji率、
长度分布、英文/术语夹杂习惯），供 Anima 在风格上逐渐向用户靠近——
三成原则：形式上向用户靠近三成，七成保持自己；形式接近，判断是她的。

存储：~/.anima/data/lang_profile.json
更新：每 UPDATE_EVERY 条用户消息触发一次轻量分析（纯 Python，不调模型）
注入：get_profile_block() 返回紧凑的风格提示，追加到 system prompt 末尾
     数据不足（< UPDATE_EVERY 条）时返回空串，不乱猜。
     每周 LLM 语体复盘产出的"她该怎么微调"建议（G1），也在此注入。
"""
from __future__ import annotations

import json
import re
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
# emoji 检测（覆盖常见 Unicode emoji 区段）
_EMOJI_RE = re.compile(
    "[\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0000FE00-\U0000FE0F"
    "]"
)
# 英文单词检测（≥2 字母才算，排除单字母噪音）
_EN_WORD_RE = re.compile(r"[a-zA-Z]{2,}")


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

    # G1 新增：emoji 使用率
    emoji_msgs = sum(1 for m in msgs if _EMOJI_RE.search(m))
    emoji_rate = round(emoji_msgs / len(msgs), 2)

    # G1 新增：消息长度分布（与上面 style 共用阈值 12/35）
    short_count = sum(1 for m in msgs if len(m) < 12)
    long_count = sum(1 for m in msgs if len(m) > 35)
    medium_count = len(msgs) - short_count - long_count
    len_distribution = {
        "short_pct": round(short_count / len(msgs), 2),
        "medium_pct": round(medium_count / len(msgs), 2),
        "long_pct": round(long_count / len(msgs), 2),
    }

    # G1 新增：英文/术语夹杂率
    en_msgs = sum(1 for m in msgs if _EN_WORD_RE.search(m))
    en_mix_rate = round(en_msgs / len(msgs), 2)

    return {
        "style":            style,
        "avg_len":          round(avg_len, 1),
        "top_endings":      top_endings,
        "top_fillers":      top_fillers,
        "punct_sparse":     punct_sparse,
        "uses_ellipsis":    uses_ellipsis,
        "emoji_rate":       emoji_rate,
        "len_distribution": len_distribution,
        "en_mix_rate":      en_mix_rate,
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
    包含：用户语言特征 + 三成原则 + 禁区清单 + LLM 语体建议（如有）。
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

        # 长度分布（提供更细粒度的节奏感知）
        ld = feat.get("len_distribution", {})
        if ld:
            dominant = max(ld, key=ld.get) if ld else ""
            if dominant == "short_pct" and ld.get("short_pct", 0) > 0.6:
                lines.append("大多是短消息（聊天感强）")
            elif dominant == "long_pct" and ld.get("long_pct", 0) > 0.4:
                lines.append("长消息占比高（倾向细说）")

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

        # G1 新增：emoji 习惯
        emoji_rate = feat.get("emoji_rate", 0)
        if emoji_rate >= 0.3:
            lines.append("常用 emoji")
        elif emoji_rate >= 0.1:
            lines.append("偶尔用 emoji")

        # G1 新增：英文夹杂
        en_mix = feat.get("en_mix_rate", 0)
        if en_mix >= 0.3:
            lines.append("中英文混着说")
        elif en_mix >= 0.1:
            lines.append("偶尔夹英文词")

        if not lines:
            return ""

        summary = "，".join(lines) + "。"

        block = (
            "\n\n## 他说话的样子（" + str(count) + " 条消息后积累）\n"
            + summary
        )

        # 三成原则 + 禁区清单（G1 核心）
        block += "\n\n### 三成原则\n"
        block += "形式上向他靠近三成，七成保持你自己。他短句多你就少写废话，"
        block += "他爱用省略号你偶尔用一个，他 emoji 多你偶尔回一个——但都是偶尔、点到为止。"
        block += "镜像太狠 = 恐怖谷 + 丢人设。他的习惯是参考，不是模板。"
        block += "\n\n### 禁区（不跟）\n"
        block += "脏话不跟、火星文不跟、叠字卖萌不跟、"
        block += "你的标点纪律不破（不滥用感叹号、不刷波浪号）。"
        block += "这些是你的底线，不管他怎么说。"

        # LLM 语体建议（G1 每周复盘产出，如有）
        advice = data.get("llm_advice", "")
        if advice:
            block += "\n\n### 本周语体微调建议\n" + advice

        return block
    except Exception:
        return ""


def save_llm_advice(advice: str) -> None:
    """保存 LLM 每周语体复盘产出的"她该怎么微调"建议（G1）。"""
    try:
        data = _load()
        data["llm_advice"] = (advice or "").strip()
        data["advice_updated"] = datetime.now(timezone.utc).isoformat()
        _save(data)
    except Exception:
        pass


def get_status() -> dict:
    """调试 / 设置页查看图谱状态。"""
    try:
        data = _load()
        return {
            "message_count": data.get("message_count", 0),
            "last_updated":  data.get("last_updated"),
            "features":      data.get("features", {}),
            "buffer_size":   len(data.get("buffer", [])),
            "llm_advice":    data.get("llm_advice", ""),
            "advice_updated": data.get("advice_updated"),
        }
    except Exception:
        return {}


def reset() -> None:
    """清空语言图谱（设置页用）。"""
    _save({"message_count": 0, "last_updated": None, "buffer": [], "features": {}})
