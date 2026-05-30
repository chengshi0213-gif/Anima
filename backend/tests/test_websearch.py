#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_websearch.py — 统一联网检索（M4）单元测试 (pytest)

不触网：stub urllib 与 config 的 key，验证
  - Tavily 优先、Serper 降级、无 key 抛 PermissionRequest；
  - 配额按月累计、跨月归零、get_usage 算剩余；
  - (query, limit) 去重缓存命中标记 cached；
  - fetch_url Jina 优先、直连兜底；
  - 共享 tool_defs / dispatch 形状正确。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_websearch.py -v
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import websearch as ws  # noqa: E402
from agent_base import PermissionRequest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # 配额文件隔离到 tmp，清缓存，默认无 key
    monkeypatch.setattr(ws, "_USAGE_FILE", tmp_path / "search_usage.json")
    ws.clear_cache()
    monkeypatch.setattr(ws._cfg, "TAVILY_KEY", "")
    monkeypatch.setattr(ws._cfg, "SERPER_KEY", "")
    monkeypatch.setattr(ws._cfg, "JINA_KEY", "")
    yield
    ws.clear_cache()


def _stub_urlopen(monkeypatch, payload: dict):
    """让 urllib.request.urlopen 返回固定 JSON。"""
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, *a): return json.dumps(payload).encode()
    monkeypatch.setattr(ws.urllib.request, "urlopen", lambda *a, **k: _Resp())


def test_no_key_raises_permission():
    with pytest.raises(PermissionRequest) as ei:
        ws.web_search("天气")
    assert "tavily_key" in ei.value.related


def test_tavily_preferred_and_counts(monkeypatch):
    monkeypatch.setattr(ws._cfg, "TAVILY_KEY", "tvly-real")
    _stub_urlopen(monkeypatch, {"results": [
        {"title": "T", "url": "http://x", "content": "snippet"}]})
    r = ws.web_search("AI 创业", limit=3)
    assert r["source"] == "tavily"
    assert r["results"][0]["title"] == "T"
    assert ws.get_usage()["tavily"] == 1
    assert ws.get_usage()["tavily_remaining"] == ws.TAVILY_FREE_MONTHLY - 1


def test_cache_hit(monkeypatch):
    monkeypatch.setattr(ws._cfg, "TAVILY_KEY", "tvly-real")
    _stub_urlopen(monkeypatch, {"results": []})
    ws.web_search("同一个问题", limit=5)
    again = ws.web_search("同一个问题", limit=5)
    assert again.get("cached") is True
    # 命中缓存不应再消耗额度
    assert ws.get_usage()["tavily"] == 1


def test_serper_fallback_when_no_tavily(monkeypatch):
    monkeypatch.setattr(ws._cfg, "SERPER_KEY", "serper-real")
    _stub_urlopen(monkeypatch, {"organic": [
        {"title": "S", "link": "http://y", "snippet": "abc"}]})
    r = ws.web_search("查询")
    assert r["source"] == "serper"
    assert ws.get_usage()["serper"] == 1


def test_usage_month_rollover(monkeypatch):
    monkeypatch.setattr(ws._cfg, "TAVILY_KEY", "tvly-real")
    _stub_urlopen(monkeypatch, {"results": []})
    ws.web_search("q1")
    # 模拟上个月的旧计数文件
    ws._USAGE_FILE.write_text(json.dumps({"month": "2000-01", "tavily": 999}), "utf-8")
    u = ws.get_usage()
    assert u["tavily"] == 0   # 跨月归零


def test_fetch_url_direct_fallback(monkeypatch):
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, *a): return b"<html><body>Hello <b>World</b></body></html>"
    monkeypatch.setattr(ws.urllib.request, "urlopen", lambda *a, **k: _Resp())
    r = ws.fetch_url("http://example.com")
    assert r["source"] == "direct"
    assert "Hello" in r["content"] and "World" in r["content"]


def test_shared_tool_defs_and_dispatch():
    names = {d["function"]["name"] for d in ws.WEB_SEARCH_TOOL_DEFS}
    assert names == {"web_search", "fetch_url"}
    d = ws.build_dispatch()
    assert set(d) == {"web_search", "fetch_url"}
    assert callable(d["web_search"]) and callable(d["fetch_url"])


def test_empty_query():
    assert ws.web_search("")["error"] == "query 为空"
