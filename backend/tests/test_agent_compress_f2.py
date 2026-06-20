#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_agent_compress_f2.py — F2 三档渐进压缩单元测试

覆盖：
  _tiered_compress 三档分区行为（近/中/远）
  _structured_compress 回退路径升级为 _tiered_compress（不再是 _compress_history）
  热区 hot_n 扩展到 12
  冷区计数占位
  中期 coding_digest 提炼（文件路径出现在中期摘要）
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_compress import AgentCompressMixin


# ── 最小可用的 Mixin 实例 ────────────────────────────────────────────

class FakeMixin(AgentCompressMixin):
    name = "test"
    coding_compress = True

    def _log(self, *a, **kw): pass

    async def _call_api(self, messages, **kw):
        return {"error": "fake"}  # always fail → 触发回退


def _user(text):
    return {"role": "user", "content": text}

def _assist(text):
    return {"role": "assistant", "content": text}

def _tool_call(fname):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"function": {"name": fname, "arguments": "{}"}}],
    }

def _tool_result(path=None):
    import json
    content = json.dumps({"path": path, "content": "x"}) if path else "{}"
    return {"role": "tool", "content": content, "tool_call_id": "tid"}


# ── TestTieredCompress ────────────────────────────────────────────────

class TestTieredCompress:
    def setup_method(self):
        self.m = FakeMixin()

    def _make_msgs(self, n, sys_n=1):
        result = [{"role": "system", "content": "sys"}] * sys_n
        result.append(_user("original task"))
        for i in range(n - 1):
            result.append(_assist(f"response {i}"))
        return result

    def test_short_messages_returned_unchanged(self):
        msgs = self._make_msgs(10)
        out = self.m._tiered_compress(msgs, hot_n=12)
        assert out == msgs

    def test_hot_zone_preserved_verbatim(self):
        msgs = [{"role": "system", "content": "S"}] + [
            _assist(f"msg {i}") for i in range(30)
        ]
        out = self.m._tiered_compress(msgs, hot_n=12, warm_n=36)
        # 最后12条应原样在结果里
        hot_contents = {m["content"] for m in msgs[-12:]}
        out_contents = {m["content"] for m in out if m.get("role") == "assistant"}
        assert hot_contents <= out_contents

    def test_cold_zone_placeholder_appears(self):
        msgs = [{"role": "system", "content": "S"}] + [
            _assist(f"msg {i}") for i in range(60)
        ]
        out = self.m._tiered_compress(msgs, hot_n=12, warm_n=20)
        # 应有远期归档占位
        placeholders = [m for m in out if "远期归档" in (m.get("content") or "")]
        assert len(placeholders) == 1

    def test_warm_zone_digest_present(self):
        """中期区域应生成结构化摘要（哪怕空的也要有占位）。"""
        msgs = [{"role": "system", "content": "S"}] + [
            _assist(f"msg {i}") for i in range(30)
        ]
        out = self.m._tiered_compress(msgs, hot_n=6, warm_n=12)
        warm_digests = [m for m in out if "中期摘要" in (m.get("content") or "")]
        assert len(warm_digests) == 1

    def test_system_msgs_always_kept(self):
        msgs = [{"role": "system", "content": "SYS"}] * 2 + [
            _assist(f"x{i}") for i in range(20)
        ]
        out = self.m._tiered_compress(msgs, hot_n=6, warm_n=6)
        sys_count = sum(1 for m in out if m.get("role") == "system")
        assert sys_count == 2

    def test_first_user_preserved(self):
        msgs = [
            {"role": "system", "content": "S"},
            _user("THE ORIGINAL TASK"),
        ] + [_assist(f"x{i}") for i in range(50)]
        out = self.m._tiered_compress(msgs, hot_n=12, warm_n=20)
        user_msgs = [m for m in out if m.get("role") == "user"]
        assert any("THE ORIGINAL TASK" in m["content"] for m in user_msgs)

    def test_file_write_appears_in_warm_digest(self):
        """中期摘要应提炼出 file_write 路径。"""
        file_write_call = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "function": {
                    "name": "file_write",
                    "arguments": '{"path": "/src/critical.py"}',
                }
            }],
        }
        msgs = [{"role": "system", "content": "S"}, _user("task")] + [
            file_write_call, _tool_result(), _assist("done"),
        ] * 8 + [_assist(f"hot{i}") for i in range(12)]
        out = self.m._tiered_compress(msgs, hot_n=12, warm_n=30)
        full_text = " ".join(m.get("content") or "" for m in out)
        assert "critical.py" in full_text


# ── TestStructuredCompressFallback ───────────────────────────────────

class TestStructuredCompressFallback:
    """验证 _structured_compress 在 LLM 失败时回退到 _tiered_compress 而非旧的 _compress_history。"""

    def setup_method(self):
        self.m = FakeMixin()

    def test_fallback_uses_tiered_not_binary(self):
        msgs = [{"role": "system", "content": "S"}] + [
            _assist(f"m{i}") for i in range(50)
        ]
        # FakeMixin._call_api 返回 error → 走 fallback
        out = asyncio.run(self.m._structured_compress(msgs))
        # tiered 结果不应该只有 "[中间对话已压缩]" 这种简单占位符
        texts = [m.get("content") or "" for m in out]
        assert any("中期摘要" in t or "远期归档" in t for t in texts), \
            "fallback 应产生 tiered 占位，而非旧式二进制压缩"

    def test_short_messages_pass_through(self):
        msgs = [_user("hi"), _assist("hello")]
        out = asyncio.run(self.m._structured_compress(msgs))
        assert out == msgs
