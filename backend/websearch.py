#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
websearch.py — 统一联网检索能力（M4）

把原本散在 xi_worker 里的 web_search / fetch_url 抽成共享模块，供任意 agent 复用：
  - web_search: 优先 Tavily（AI 原生）→ Serper（Google）→ 抛 PermissionRequest 引导配置；
  - fetch_url:  优先 Jina AI Reader（结构化抽取）→ 直接 HTTP 兜底；
  - 配额统计: 按自然月累计各 provider 调用次数，持久化到 DATA_DIR/search_usage.json，
              Tavily 免费额度约 1000/月，可通过 get_usage() 查看剩余；
  - 去重缓存: (query, limit) 命中 TTL 内的结果直接返回，省额度、提速。

各 worker 通过 WEB_SEARCH_TOOL_DEFS + build_dispatch() 共享同一套工具定义与分发，
保证四人格的联网行为一致。
"""
from __future__ import annotations

import json
import time
import threading
import urllib.request
from datetime import date

import config as _cfg
from agent_base import PermissionRequest
from config import DATA_DIR

# ── 配额 ───────────────────────────────────────────────
TAVILY_FREE_MONTHLY = 1000          # Tavily 免费额度（约）
_USAGE_FILE = DATA_DIR / "search_usage.json"
_usage_lock = threading.Lock()

# ── 去重缓存 ────────────────────────────────────────────
_CACHE_TTL = 600                    # 10 分钟
_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _has_key(key: str | None) -> bool:
    return bool(key) and not key.startswith("sk-xxx")


# ══════════════════════════════════════════════════════
#  配额统计
# ══════════════════════════════════════════════════════

def _load_usage() -> dict:
    if _USAGE_FILE.exists():
        try:
            return json.loads(_USAGE_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {}


def _current_month() -> str:
    return date.today().strftime("%Y-%m")


def _bump_usage(provider: str) -> None:
    """某 provider 成功调用一次，累加当月计数（跨月自动归零）。"""
    month = _current_month()
    with _usage_lock:
        data = _load_usage()
        if data.get("month") != month:
            data = {"month": month}
        data[provider] = int(data.get(provider, 0)) + 1
        try:
            _USAGE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass


def get_usage() -> dict:
    """返回当月各 provider 用量 + Tavily 剩余额度（供 /search/usage 路由）。"""
    month = _current_month()
    data = _load_usage()
    if data.get("month") != month:
        data = {"month": month}
    tavily = int(data.get("tavily", 0))
    serper = int(data.get("serper", 0))
    return {
        "month":          month,
        "tavily":         tavily,
        "serper":         serper,
        "jina":           int(data.get("jina", 0)),
        "tavily_limit":   TAVILY_FREE_MONTHLY,
        "tavily_remaining": max(0, TAVILY_FREE_MONTHLY - tavily),
    }


# ══════════════════════════════════════════════════════
#  缓存
# ══════════════════════════════════════════════════════

def _cache_get(key: tuple) -> dict | None:
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL:
            return hit[1]
        if hit:
            _cache.pop(key, None)
    return None


def _cache_put(key: tuple, value: dict) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# ══════════════════════════════════════════════════════
#  联网搜索
# ══════════════════════════════════════════════════════

def web_search(query: str, limit: int = 8) -> dict:
    """联网搜索。优先 Tavily → Serper → 抛 PermissionRequest。

    可能抛出 PermissionRequest（无任何搜索 Key），由 AgentBase 工具分发向上传播，
    websocket_server 捕获后推送权限请求卡片。
    """
    query = (query or "").strip()
    if not query:
        return {"error": "query 为空", "results": []}

    cache_key = ("search", query, int(limit))
    cached = _cache_get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    # ── Tavily（首选，AI 原生搜索）──
    tavily_key = _cfg.TAVILY_KEY
    if _has_key(tavily_key):
        try:
            payload = json.dumps({
                "api_key": tavily_key,
                "query": query,
                "max_results": limit,
                "search_depth": "basic",
            }).encode()
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            results = [
                {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
                for r in data.get("results", [])
            ]
            out = {"source": "tavily", "results": results}
            _bump_usage("tavily")
            _cache_put(cache_key, out)
            return out
        except Exception:
            pass   # 失败降级到 Serper

    # ── Serper（Google 搜索 API）──
    serper_key = _cfg.SERPER_KEY
    if _has_key(serper_key):
        try:
            payload = json.dumps({"q": query, "num": limit}).encode()
            req = urllib.request.Request(
                "https://google.serper.dev/search",
                data=payload,
                headers={"Content-Type": "application/json", "X-API-KEY": serper_key},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            results = [
                {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
                for r in data.get("organic", [])
            ]
            out = {"source": "serper", "results": results}
            _bump_usage("serper")
            _cache_put(cache_key, out)
            return out
        except Exception:
            pass

    # ── 无可用搜索 API，抛出权限请求 ──
    raise PermissionRequest(
        api_name="搜索 API",
        reason="执行联网搜索需要配置 Tavily 或 Serper API Key。Tavily 每月免费 1000 次，完全够用。",
        signup_url="https://tavily.com",
        alternatives=["Serper (Google)", "Jina AI Reader"],
        related=["tavily_key", "serper_key"],
    )


def fetch_url(url: str, use_jina: bool = True) -> dict:
    """读取网页正文。优先 Jina AI Reader（结构化抽取），兜底直接 HTTP。"""
    jina_key = _cfg.JINA_KEY
    if use_jina and _has_key(jina_key):
        try:
            jina_url = f"https://r.jina.ai/{url}"
            req = urllib.request.Request(
                jina_url,
                headers={"Authorization": f"Bearer {jina_key}", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            _bump_usage("jina")
            return {
                "source": "jina",
                "url": url,
                "title": data.get("data", {}).get("title", ""),
                "content": data.get("data", {}).get("content", "")[:8000],
            }
        except Exception:
            pass

    # 兜底：直接抓取（无 API Key 也能用，但无结构化）
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Anima/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(200_000).decode("utf-8", errors="replace")
        import re
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        return {"source": "direct", "url": url, "content": text[:6000]}
    except Exception as e:
        return {"error": str(e), "url": url}


# ══════════════════════════════════════════════════════
#  共享工具定义 / 分发（任意 worker 复用）
# ══════════════════════════════════════════════════════

WEB_SEARCH_TOOL_DEFS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "联网搜索。使用 Tavily 或 Serper 搜索实时信息、新闻、文档等。需要配置搜索 API Key。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索查询词"},
            "limit": {"type": "integer", "description": "最多返回结果数（默认8）"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "fetch_url",
        "description": "读取指定 URL 的网页正文内容。使用 Jina AI Reader 获得更好的结构化提取。",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "要读取的网页 URL"},
        }, "required": ["url"]},
    }},
]


def build_dispatch() -> dict:
    """返回 {tool_name: callable} 分发表，合并进 worker 的 tool_dispatch。"""
    return {
        "web_search": lambda **kw: web_search(kw["query"], kw.get("limit", 8)),
        "fetch_url":  lambda **kw: fetch_url(kw["url"]),
    }
