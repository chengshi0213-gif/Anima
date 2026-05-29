#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_engine_core.py — Agent 引擎核心 + 搜索引擎 单元测试 (pytest)

覆盖这些"改一行就可能静默崩"的关键路径：
  - AgentBase._handle_stream  : 流式 tool_call delta 增量累加（含多 index）
  - AgentBase._compress_history: 历史压缩保留 system+首条+尾部
  - AgentBase._trim_result     : 工具结果去重的 per-run 隔离 + file_read 指纹
  - AgentBase._resolve_model   : 中转模型缺 relay_url 抛 PermissionRequest
  - AgentBase.run              : token 预算护栏触发 budget_exceeded
  - SearchEngine               : agent 过滤参数化（防注入）+ 重索引去重

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_engine_core.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

# ── 确保 backend 目录在 sys.path ──
_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from agent_base import AgentBase, PermissionRequest, MODEL_REGISTRY  # noqa: E402
from search_engine import SearchEngine  # noqa: E402


# ════════════════════════════════════════════════════════════════════
#  fixtures / helpers
# ════════════════════════════════════════════════════════════════════

def _make_agent(tmp_path, **over):
    """构造一个最小可用的 AgentBase（日志/工作区指向临时目录）。"""
    return AgentBase(
        name="test",
        api_key="dummy-key",
        model="dummy-model",
        base_url="https://example.invalid",
        system_prompt="SP",
        tool_defs=[],
        tool_dispatch={},
        log_dir=tmp_path / "logs",
        work_dir=tmp_path / "work",
        **over,
    )


class _FakeContent:
    """模拟 aiohttp resp.content：异步迭代逐行 bytes。"""
    def __init__(self, lines):
        self._lines = lines

    def __aiter__(self):
        async def gen():
            for ln in self._lines:
                yield ln
        return gen()


class _FakeResp:
    def __init__(self, lines):
        self.content = _FakeContent(lines)


def _sse(obj) -> bytes:
    return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def _delta(d) -> bytes:
    return _sse({"choices": [{"delta": d}]})


# ════════════════════════════════════════════════════════════════════
#  _handle_stream — 流式 tool_call 增量累加
# ════════════════════════════════════════════════════════════════════

def test_handle_stream_accumulates_single_tool_call(tmp_path):
    agent = _make_agent(tmp_path)
    lines = [
        _delta({"content": "想一下"}),
        _delta({"reasoning_content": "推理片段"}),
        _delta({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                "function": {"name": "search_code", "arguments": ""}}]}),
        _delta({"tool_calls": [{"index": 0, "function": {"arguments": '{"pat'}}]}),
        _delta({"tool_calls": [{"index": 0, "function": {"arguments": 'tern":"x"}'}}]}),
        b"data: [DONE]\n",
    ]
    out = asyncio.run(agent._handle_stream(_FakeResp(lines)))

    assert out["content"] == "想一下"
    assert out["reasoning_content"] == "推理片段"
    assert out["tool_calls"] is not None and len(out["tool_calls"]) == 1
    tc = out["tool_calls"][0]
    assert tc["id"] == "call_1"
    assert tc["function"]["name"] == "search_code"
    # 关键：参数跨 3 个 chunk 正确拼接
    assert json.loads(tc["function"]["arguments"]) == {"pattern": "x"}


def test_handle_stream_multiple_tool_calls_by_index(tmp_path):
    agent = _make_agent(tmp_path)
    lines = [
        _delta({"tool_calls": [{"index": 0, "id": "c0", "function": {"name": "a", "arguments": "{}"}}]}),
        _delta({"tool_calls": [{"index": 1, "id": "c1", "function": {"name": "b", "arguments": ""}}]}),
        _delta({"tool_calls": [{"index": 1, "function": {"arguments": '{"k":1}'}}]}),
        b"data: [DONE]\n",
    ]
    out = asyncio.run(agent._handle_stream(_FakeResp(lines)))
    assert len(out["tool_calls"]) == 2
    assert out["tool_calls"][0]["function"]["name"] == "a"
    assert out["tool_calls"][1]["function"]["name"] == "b"
    assert json.loads(out["tool_calls"][1]["function"]["arguments"]) == {"k": 1}


def test_handle_stream_no_tool_calls(tmp_path):
    agent = _make_agent(tmp_path)
    lines = [_delta({"content": "纯文本回复"}), b"data: [DONE]\n"]
    out = asyncio.run(agent._handle_stream(_FakeResp(lines)))
    assert out["content"] == "纯文本回复"
    assert out["tool_calls"] is None


def test_handle_stream_ignores_malformed_chunks(tmp_path):
    agent = _make_agent(tmp_path)
    lines = [
        b"data: not-json\n",
        b": comment line\n",
        _delta({"content": "ok"}),
        b"data: [DONE]\n",
    ]
    out = asyncio.run(agent._handle_stream(_FakeResp(lines)))
    assert out["content"] == "ok"


# ════════════════════════════════════════════════════════════════════
#  _compress_history
# ════════════════════════════════════════════════════════════════════

def test_compress_history_noop_when_short(tmp_path):
    agent = _make_agent(tmp_path)
    msgs = [{"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"}]
    assert agent._compress_history(msgs) == msgs


def test_compress_history_keeps_system_first_and_tail(tmp_path):
    agent = _make_agent(tmp_path)
    msgs = [{"role": "system", "content": "SYS"},
            {"role": "user", "content": "FIRST_USER"}]
    for i in range(20):
        msgs.append({"role": "assistant", "content": f"a{i}"})
        msgs.append({"role": "user", "content": f"u{i}"})

    out = agent._compress_history(msgs)
    assert len(out) < len(msgs)
    assert out[0]["role"] == "system" and out[0]["content"] == "SYS"
    # 首条 user 被保留
    assert any(m.get("content") == "FIRST_USER" for m in out)
    # 有压缩占位符
    assert any(m.get("content") == "[中间对话已压缩]" for m in out)
    # 尾部最近的消息保留
    assert out[-1] == msgs[-1]


# ════════════════════════════════════════════════════════════════════
#  _trim_result — per-run 去重隔离
# ════════════════════════════════════════════════════════════════════

def test_trim_result_dedup_within_same_seen(tmp_path):
    agent = _make_agent(tmp_path)
    seen: set[str] = set()
    r = {"results": ["same"]}
    first = agent._trim_result("search_code", r, seen)
    second = agent._trim_result("search_code", r, seen)
    assert "_dedup" not in first
    assert json.loads(second).get("_dedup") is True


def test_trim_result_isolation_across_runs(tmp_path):
    """两个独立 run（独立 seen 集合）不应相互污染——P0 修复的核心保证。"""
    agent = _make_agent(tmp_path)
    seen_a: set[str] = set()
    seen_b: set[str] = set()
    r = {"results": ["same payload"]}
    out_a = agent._trim_result("search_code", r, seen_a)
    out_b = agent._trim_result("search_code", r, seen_b)
    # run B 第一次看到该内容，必须拿到完整结果而非被 A 误判 _dedup
    assert "_dedup" not in out_a
    assert "_dedup" not in out_b
    assert "same payload" in out_b


def test_trim_result_file_read_fingerprint(tmp_path):
    agent = _make_agent(tmp_path)
    big = {"content": "x" * 5000, "path": "/f"}
    out = agent._trim_result("file_read", big, set())
    d = json.loads(out)
    assert "fingerprint" in d


# ════════════════════════════════════════════════════════════════════
#  _resolve_model — 中转模型缺 relay_url 抛 PermissionRequest
# ════════════════════════════════════════════════════════════════════

def test_resolve_model_falls_back_to_default(tmp_path):
    agent = _make_agent(tmp_path)
    key, base, model = agent._resolve_model(None)
    assert base == "https://example.invalid"
    assert model == "dummy-model"


def test_resolve_model_relay_without_url_raises(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    # 模拟：配置了 key 但 base_url 为空（relay_url 未设置）
    monkeypatch.setitem(MODEL_REGISTRY, "FakeRelay",
                        (lambda: "sk-has-key", "", "fake-relay-model"))
    with pytest.raises(PermissionRequest) as ei:
        agent._resolve_model("FakeRelay")
    assert "relay_url" in ei.value.related


# ════════════════════════════════════════════════════════════════════
#  run — token 预算护栏
# ════════════════════════════════════════════════════════════════════

def test_run_budget_guardrail(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    agent.max_total_chars = 5   # 极低预算，首轮即触发

    # 让记忆注入返回空，避免依赖真实后端
    import memory_injector as mi
    monkeypatch.setattr(mi, "get_memory_injection", lambda *a, **k: "")
    monkeypatch.setattr(mi, "get_active_project_context", lambda *a, **k: "")

    # _call_api 不应被调用到（预算检查在调用前），但兜底 stub 一个
    async def _never(*a, **k):
        return {"content": "should-not-reach", "tool_calls": None}
    monkeypatch.setattr(agent, "_call_api", _never)

    out = asyncio.run(agent.run("一个任务", session_id="test-budget"))
    assert out["status"] == "budget_exceeded"
    assert out["turn_count"] == 1


# ════════════════════════════════════════════════════════════════════
#  SearchEngine — 参数化防注入 + 重索引去重
# ════════════════════════════════════════════════════════════════════

@pytest.fixture
def engine(tmp_path):
    se = SearchEngine(tmp_path / "search.db")
    yield se
    se.close()


def test_search_agent_filter(engine):
    engine.index_session("s1", "xi", [{"role": "user", "content": "apple price 苹果"}])
    engine.index_session("s2", "tianyuan", [{"role": "user", "content": "apple market 苹果"}])
    assert len(engine.search("apple")) == 2
    assert [r["agent"] for r in engine.search("apple", agent="xi")] == ["xi"]
    assert [r["agent"] for r in engine.search("apple", agent="tianyuan")] == ["tianyuan"]


def test_search_injection_safe(engine):
    engine.index_session("s1", "xi", [{"role": "user", "content": "apple"}])
    # 注入串被当作字面 agent 名，匹配不到任何会话 → 空，且不报错
    assert engine.search("apple", agent="xi' OR '1'='1") == []


def test_reindex_dedup(engine):
    msgs = [{"role": "user", "content": "苹果 apple"},
            {"role": "assistant", "content": "天气"}]
    engine.index_session("s1", "xi", msgs)
    engine.index_session("s1", "xi", msgs)  # 重复索引同一会话
    engine.index_session("s1", "xi", msgs)
    # 去重生效：apple 只在 s1 出现一次，不翻倍
    assert len(engine.search("apple")) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
