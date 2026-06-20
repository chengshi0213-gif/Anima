#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_agent_resilience_f3.py — F3 容错 JSON 参数解析单元测试

覆盖：
  _tolerant_parse_args: 直接 JSON / markdown 包裹 / 散文中提取 / 完全无效
  _execute_tools_maybe_parallel: 畸形 args 经容错修复后能继续执行（不立即报错）
                                  完全无法修复时返回结构化错误提示
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_resilience import AgentResilienceMixin


# ── _tolerant_parse_args ────────────────────────────────────────────

class TestTolerantParseArgs:
    def test_valid_json_direct(self):
        r = AgentResilienceMixin._tolerant_parse_args('{"path": "/x.py"}')
        assert r == {"path": "/x.py"}

    def test_markdown_wrapped_json(self):
        raw = '```json\n{"key": "value"}\n```'
        r = AgentResilienceMixin._tolerant_parse_args(raw)
        assert r == {"key": "value"}

    def test_markdown_no_lang(self):
        raw = '```\n{"a": 1}\n```'
        r = AgentResilienceMixin._tolerant_parse_args(raw)
        assert r == {"a": 1}

    def test_json_embedded_in_prose(self):
        raw = 'Here is the call: {"file": "foo.py", "content": "x"} done.'
        r = AgentResilienceMixin._tolerant_parse_args(raw)
        assert r == {"file": "foo.py", "content": "x"}

    def test_empty_object(self):
        r = AgentResilienceMixin._tolerant_parse_args("{}")
        assert r == {}

    def test_truly_invalid_returns_none(self):
        r = AgentResilienceMixin._tolerant_parse_args("this is not json at all")
        assert r is None

    def test_single_quoted_returns_none(self):
        # single-quote JSON is not valid JSON and not fixable by our strategies
        r = AgentResilienceMixin._tolerant_parse_args("{'key': 'val'}")
        assert r is None

    def test_nested_json(self):
        raw = '{"options": {"flag": true, "count": 3}}'
        r = AgentResilienceMixin._tolerant_parse_args(raw)
        assert r["options"]["flag"] is True


# ── _execute_tools_maybe_parallel — F3 路径 ────────────────────────

class FakeMixin(AgentResilienceMixin):
    """最小 Mixin 实现，供并行执行测试用。"""

    def _log(self, *a, **kw): pass

    async def _execute_tool(self, name: str, args: dict, ctx=None) -> dict:
        return {"ok": True, "name": name, "args": args}


def _tc(name: str, raw_args: str) -> dict:
    return {"id": "tc1", "function": {"name": name, "arguments": raw_args}}


class TestExecuteToolsF3:
    def setup_method(self):
        self.mixin = FakeMixin()
        self.fail_counts: dict = {}

    def _run(self, tool_calls):
        return asyncio.run(
            self.mixin._execute_tools_maybe_parallel(
                tool_calls, self.fail_counts, ctx=None
            )
        )

    def test_valid_args_executes_normally(self):
        results = self._run([_tc("file_read", '{"path": "/x.py"}')])
        assert len(results) == 1
        tc, name, args, result = results[0]
        assert name == "file_read"
        assert result.get("ok") is True
        assert args == {"path": "/x.py"}

    def test_markdown_wrapped_args_recovered(self):
        """弱模型输出 markdown 包裹的 args，容错修复后正常执行。"""
        raw = '```json\n{"path": "/recovered.py"}\n```'
        results = self._run([_tc("file_read", raw)])
        tc, name, args, result = results[0]
        assert result.get("ok") is True
        assert args.get("path") == "/recovered.py"

    def test_json_in_prose_recovered(self):
        """散文中内嵌 JSON，能提取后继续执行。"""
        raw = 'I will read: {"path": "/inline.py"} here.'
        results = self._run([_tc("file_read", raw)])
        tc, name, args, result = results[0]
        assert result.get("ok") is True

    def test_unrepairable_args_returns_structured_error(self):
        """完全无效的 args → 返回结构化错误，不抛异常。"""
        results = self._run([_tc("file_read", "not json at all")])
        tc, name, args, result = results[0]
        assert "error" in result
        assert "容错修复" in result["error"]
        assert "合法 JSON" in result["error"]

    def test_empty_object_args_executes(self):
        results = self._run([_tc("list_dir", "{}")])
        tc, name, args, result = results[0]
        assert result.get("ok") is True
        assert args == {}
