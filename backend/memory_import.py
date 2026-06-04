#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_import.py — Transfer Memory（从别的 AI 把记忆带进 Anima）

用户把 ChatGPT / Claude / Cursor 等导出的文本粘进来，守藏（或首个可用模型）
把其中关于「用户本人」的长期事实提炼成记忆条，写入本地记忆库。
绝不联网上传——只在本地模型 API 调用层处理。
"""
from __future__ import annotations

import json
import re

import aiohttp

_MAX_CHARS = 24000          # 单次最多处理的字符（防超长 token）
_MAX_ENTRIES = 40           # 单次最多写入条数（防刷爆）

_EXTRACT_SYS = (
    "你是 Anima 的记忆整理员。用户给你一段从别的 AI 助手导出的对话/资料，"
    "请只提炼其中关于【用户本人】的、值得长期记住的稳定事实："
    "身份背景、职业、长期目标、偏好、重要关系、正在做的项目、口味禁忌等。"
    "忽略一次性的闲聊、AI 的回答、与用户无关的通用知识。"
    "输出严格的 JSON 数组，每项形如 "
    '{"key":"简短标题","value":"具体内容（第三人称，如：用户……）",'
    '"category":"identity|preference|goal|relationship|project|general",'
    '"importance":1-5}。'
    "只输出 JSON，不要任何解释、不要 markdown 代码围栏。最多 40 条。"
)


def _strip_fences(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _parse_entries(raw: str) -> list[dict]:
    txt = _strip_fences(raw)
    # 容错：截取第一个 [ 到最后一个 ]
    if "[" in txt and "]" in txt:
        txt = txt[txt.index("["): txt.rindex("]") + 1]
    try:
        data = json.loads(txt)
    except Exception:
        return []
    out = []
    for it in data if isinstance(data, list) else []:
        if not isinstance(it, dict):
            continue
        k = str(it.get("key", "")).strip()[:80]
        v = str(it.get("value", "")).strip()[:600]
        if not k or not v:
            continue
        cat = str(it.get("category", "general")).strip() or "general"
        try:
            imp = max(1, min(5, int(it.get("importance", 3))))
        except Exception:
            imp = 3
        out.append({"key": k, "value": v, "category": cat, "importance": imp})
        if len(out) >= _MAX_ENTRIES:
            break
    return out


async def _extract_via_llm(text: str) -> list[dict]:
    """调用首个已配置的模型提炼记忆条。无 key 时抛异常，由上层降级。"""
    from agent_base import first_available_model
    api_key, base_url, model_id = first_available_model()
    if not (api_key and base_url):
        raise RuntimeError("no_model")
    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": _EXTRACT_SYS},
            {"role": "user", "content": text[:_MAX_CHARS]},
        ],
        "stream": False,
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as sess:
        async with sess.post(f"{base_url}/chat/completions", headers=headers, json=body,
                             timeout=aiohttp.ClientTimeout(total=120)) as r:
            if r.status != 200:
                raise RuntimeError(f"api_{r.status}")
            data = await r.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return _parse_entries(content)


async def import_text(text: str, source: str = "", agent_id: str | None = "xi") -> dict:
    """
    把一段外部文本提炼并写入记忆库。
    返回 {ok, imported, entries:[...], mode:"llm"|"raw"}。
    """
    import asyncio
    from memory_injector import write_memory

    text = (text or "").strip()
    if len(text) < 8:
        return {"ok": False, "error": "内容太短"}

    src_tag = f"[导入自 {source}] " if source else "[导入] "
    mode = "llm"
    try:
        entries = await _extract_via_llm(text)
    except Exception:
        entries = []
    if not entries:
        # 降级：整段作为一条记忆存档（截断），不丢用户数据
        mode = "raw"
        entries = [{
            "key": f"{source or '外部'}导入资料",
            "value": text[:600],
            "category": "general",
            "importance": 2,
        }]

    written = []
    for e in entries:
        try:
            eid = await asyncio.to_thread(
                write_memory, e["key"], src_tag + e["value"],
                e["category"], agent_id, e["importance"],
            )
            written.append({**e, "id": eid})
        except Exception:
            continue

    return {"ok": True, "imported": len(written), "entries": written, "mode": mode}
