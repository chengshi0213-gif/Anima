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


def test_handle_stream_empty_choices_chunk(tmp_path):
    """回归：DeepSeek/Qwen 末尾常发 choices=[] 的 usage 统计 chunk，
    不能让 [0] 越界（曾导致晞排盘时 IndexError）。"""
    agent = _make_agent(tmp_path)
    lines = [
        _delta({"content": "正常内容"}),
        _sse({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}),
        b"data: [DONE]\n",
    ]
    out = asyncio.run(agent._handle_stream(_FakeResp(lines)))
    assert out["content"] == "正常内容"
    assert out["tool_calls"] is None


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


def test_coding_compress_off_by_default(tmp_path):
    """默认 coding_compress=False：占位符就是裸字符串，不带摘要。"""
    agent = _make_agent(tmp_path)
    assert agent.coding_compress is False
    msgs = [{"role": "system", "content": "SYS"},
            {"role": "user", "content": "FIRST"}]
    for i in range(10):
        msgs.append({"role": "assistant", "tool_calls": [
            {"id": f"c{i}", "type": "function",
             "function": {"name": "file_edit",
                          "arguments": json.dumps({"path": f"f{i}.py",
                                                   "old_string": "a", "new_string": "b"})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": "{}"})
    out = agent._compress_history(msgs)
    assert any(m.get("content") == "[中间对话已压缩]" for m in out)


def test_coding_compress_digests_files_and_commands(tmp_path):
    """coding_compress=True：占位符里带上"已改文件 + 关键命令/退出码"摘要。"""
    agent = _make_agent(tmp_path)
    agent.coding_compress = True
    msgs = [{"role": "system", "content": "SYS"},
            {"role": "user", "content": "FIRST"}]
    # 中间：改了 calc.py、跑了 pytest（exit=0）
    msgs.append({"role": "assistant", "tool_calls": [
        {"id": "e1", "type": "function",
         "function": {"name": "file_edit",
                      "arguments": json.dumps({"path": "calc.py",
                                               "old_string": "x", "new_string": "y"})}}]})
    msgs.append({"role": "tool", "tool_call_id": "e1", "content": json.dumps({"replaced": 1})})
    msgs.append({"role": "assistant", "tool_calls": [
        {"id": "s1", "type": "function",
         "function": {"name": "shell_run",
                      "arguments": json.dumps({"command": "pytest -q"})}}]})
    msgs.append({"role": "tool", "tool_call_id": "s1",
                 "content": json.dumps({"exit_code": 0, "stdout": "1 passed"})})
    # 再灌一堆消息把上面挤进"被压缩"区间
    for i in range(8):
        msgs.append({"role": "assistant", "content": f"a{i}"})
        msgs.append({"role": "user", "content": f"u{i}"})

    out = agent._compress_history(msgs)
    ph = next(m["content"] for m in out
              if m["role"] == "assistant" and "[中间对话已压缩]" in (m.get("content") or ""))
    assert "calc.py" in ph
    assert "pytest -q" in ph and "exit=0" in ph


def test_compress_history_no_orphan_tool_at_tail_head(tmp_path):
    """回归：tail 切片若落在工具调用序列中间，会把对应 assistant.tool_calls
    压缩掉、只剩孤儿 tool 消息开头 → 供应商 400
    'tool must be a response to a preceding message with tool_calls'。
    压缩后 tail 的首条业务消息绝不能是 role=tool。"""
    agent = _make_agent(tmp_path)
    msgs = [{"role": "system", "content": "SYS"},
            {"role": "user", "content": "FIRST_USER"}]
    # 制造交替的 assistant(tool_calls)+tool 序列，使 rest[-6:] 大概率切进中间
    for i in range(10):
        msgs.append({"role": "assistant",
                     "tool_calls": [{"id": f"c{i}", "type": "function",
                                     "function": {"name": "t", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": "r"})

    out = agent._compress_history(msgs)
    # 压缩占位符之后、真正 tail 的第一条不得是孤儿 tool
    # 找到第一条非 system、非占位符 assistant 的消息
    placeholder = "[中间对话已压缩]"
    body = [m for m in out
            if not (m["role"] == "system")
            and not (m["role"] == "assistant" and m.get("content") == placeholder)
            and not (m["role"] == "user" and m.get("content") == "FIRST_USER")]
    if body:
        assert body[0]["role"] != "tool", "tail 不能以孤儿 tool 消息开头"
    # 每个 tool 消息前必有带 tool_calls 的 assistant（整体配对完整性）
    for i, m in enumerate(out):
        if m["role"] == "tool":
            assert i > 0 and out[i - 1].get("tool_calls"), \
                "tool 消息必须紧跟在 assistant.tool_calls 之后"


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


def test_trim_result_caps_are_per_agent(tmp_path):
    """M8 grounding：工具结果截断上限可 per-agent 覆盖。
    默认档把代码截到 500（聊天人格友好）；编程 agent 调大后能真看见代码，
    file_read 大文件也不再被降级成指纹。"""
    agent = _make_agent(tmp_path)
    # 默认值
    assert agent.tool_result_cap == 500
    assert agent.file_read_cap == 2048

    code = {"content": "c" * 6000, "path": "/big.py"}
    # 默认档：file_read 超 2048 → 只回指纹（半瞎）
    default_out = agent._trim_result("file_read", code, set())
    assert "fingerprint" in json.loads(default_out)

    # 编程档：调大两个 cap 后，完整内容回传（真看得见）
    agent.tool_result_cap = 16000
    agent.file_read_cap = 24000
    full_out = agent._trim_result("file_read", code, set())
    assert "fingerprint" not in full_out
    assert "c" * 6000 in full_out


# ════════════════════════════════════════════════════════════════════
#  H2: 缓存友好压缩——阈值触发
# ════════════════════════════════════════════════════════════════════

def test_h2_compress_threshold_attr(tmp_path):
    agent = _make_agent(tmp_path)
    assert hasattr(agent, "compress_threshold")
    assert agent.compress_threshold == 0.7


def test_h2_compress_history_still_works(tmp_path):
    """_compress_history 本身行为不变：>10 条就压缩。"""
    agent = _make_agent(tmp_path)
    msgs = [{"role": "system", "content": "s"},
            {"role": "user", "content": "u"}]
    for i in range(20):
        msgs.append({"role": "assistant", "content": f"a{i}"})
        msgs.append({"role": "user", "content": f"q{i}"})
    out = agent._compress_history(msgs)
    assert len(out) < len(msgs)


def test_h2_short_history_no_compress(tmp_path):
    """<= 10 条消息不压缩（旧行为保持）。"""
    agent = _make_agent(tmp_path)
    msgs = [{"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "q"}]
    out = agent._compress_history(msgs)
    assert len(out) == len(msgs)

    # 普通工具结果同样受 tool_result_cap 控制
    small = _make_agent(tmp_path / "b")
    long_text = {"results": "y" * 3000}
    assert "[截断" in small._trim_result("search_code", long_text, set())  # 默认 500 截断
    small.tool_result_cap = 16000
    assert "[截断" not in small._trim_result("search_code", long_text, set())


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


# ════════════════════════════════════════════════════════════════════
#  H3: 结构化压缩 _structured_compress
# ════════════════════════════════════════════════════════════════════

def test_h3_short_history_unchanged(tmp_path):
    """<= 10 条消息直接原样返回，不触发 LLM。"""
    agent = _make_agent(tmp_path)
    msgs = [{"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"}]
    out = asyncio.run(agent._structured_compress(msgs))
    assert out is msgs


def test_h3_fallback_on_llm_failure(tmp_path, monkeypatch):
    """LLM 调用失败时回退到 _compress_history。"""
    agent = _make_agent(tmp_path)
    msgs = [{"role": "system", "content": "sys"}]
    msgs.append({"role": "user", "content": "first question"})
    for i in range(20):
        msgs.append({"role": "assistant", "content": f"ans-{i}"})
        msgs.append({"role": "user", "content": f"q-{i}"})

    async def _fail_api(*a, **k):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(agent, "_call_api", _fail_api)

    out = asyncio.run(agent._structured_compress(msgs))
    assert len(out) < len(msgs)
    assert any("[中间对话已压缩]" in m.get("content", "") for m in out)


def test_h3_structured_summary_used(tmp_path, monkeypatch):
    """LLM 成功时用结构化摘要替代占位符。"""
    agent = _make_agent(tmp_path)
    msgs = [{"role": "system", "content": "sys"}]
    msgs.append({"role": "user", "content": "first question"})
    for i in range(20):
        msgs.append({"role": "assistant", "content": f"ans-{i}"})
        msgs.append({"role": "user", "content": f"q-{i}"})

    fake_summary = "1. 原始任务：测试\n2. 技术决策：选A\n3. 已改文件：无\n" \
                   "4. 踩过的错：无\n5. 关键代码：无\n6. 用户插话：无\n" \
                   "7. 待办事项：无\n8. 当前进展：测试中"

    async def _ok_api(*a, **k):
        return {"content": fake_summary}
    monkeypatch.setattr(agent, "_call_api", _ok_api)

    out = asyncio.run(agent._structured_compress(msgs))
    summary_msg = [m for m in out if "结构化摘要" in m.get("content", "")]
    assert len(summary_msg) == 1
    assert "原始任务" in summary_msg[0]["content"]
    assert out[0]["role"] == "system"
    assert out[1]["role"] == "user"
    assert out[1]["content"] == "first question"


def test_h3_empty_summary_triggers_fallback(tmp_path, monkeypatch):
    """LLM 返回空/过短摘要时回退。"""
    agent = _make_agent(tmp_path)
    msgs = [{"role": "system", "content": "s"},
            {"role": "user", "content": "u"}]
    for i in range(20):
        msgs.append({"role": "assistant", "content": f"a{i}"})
        msgs.append({"role": "user", "content": f"q{i}"})

    async def _short_api(*a, **k):
        return {"content": "too short"}
    monkeypatch.setattr(agent, "_call_api", _short_api)

    out = asyncio.run(agent._structured_compress(msgs))
    assert any("[中间对话已压缩]" in m.get("content", "") for m in out)


def test_h3_tool_calls_rendered(tmp_path, monkeypatch):
    """含 tool_calls 的消息在 history_lines 里显示工具名。"""
    agent = _make_agent(tmp_path)
    msgs = [{"role": "system", "content": "s"},
            {"role": "user", "content": "u"}]
    for i in range(15):
        msgs.append({"role": "assistant", "content": f"a{i}",
                      "tool_calls": [{"function": {"name": f"tool_{i}"}}]})
        msgs.append({"role": "user", "content": f"q{i}"})

    captured_prompt = {}

    async def _capture_api(messages, **k):
        captured_prompt["text"] = messages[0]["content"]
        return {"content": "1. 原始任务：x\n2. 技术决策：y\n3. 已改文件：z\n"
                           "4. 踩过的错：无\n5. 关键代码：无\n6. 用户插话：无\n"
                           "7. 待办事项：无\n8. 当前进展：做完了这个很长的摘要内容"}
    monkeypatch.setattr(agent, "_call_api", _capture_api)

    asyncio.run(agent._structured_compress(msgs))
    assert "调用工具" in captured_prompt["text"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
