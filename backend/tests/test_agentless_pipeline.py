#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_agentless_pipeline.py — Phase D Agentless 管道单元测试

全部离线：LLM 调用通过 monkeypatch 注入 fake；不消耗 API 额度。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentless_pipeline import (
    _parse_patch,
    _apply_changes,
    _build_patch_messages,
    _build_repair_messages,
    AgentlessPipeline,
    PipelineResult,
)


# ── _parse_patch ──────────────────────────────────────────────────────────────

class TestParsePatch:
    def test_clean_json(self):
        raw = json.dumps({
            "changes": [{"file": "a.py", "old": "x = 1", "new": "x = 2"}],
            "explanation": "fix x",
        })
        assert _parse_patch(raw) == [{"file": "a.py", "old": "x = 1", "new": "x = 2"}]

    def test_markdown_wrapped_json(self):
        raw = "```json\n" + json.dumps({
            "changes": [{"file": "b.py", "old": "y", "new": "z"}],
        }) + "\n```"
        result = _parse_patch(raw)
        assert result == [{"file": "b.py", "old": "y", "new": "z"}]

    def test_markdown_no_lang(self):
        raw = "```\n" + json.dumps({
            "changes": [{"file": "c.py", "old": "a", "new": "b"}],
        }) + "\n```"
        assert _parse_patch(raw)[0]["file"] == "c.py"

    def test_json_embedded_in_prose(self):
        inner = json.dumps({"changes": [{"file": "x.py", "old": "1", "new": "2"}]})
        raw = f"Here's my fix:\n{inner}\nDone."
        assert _parse_patch(raw) == [{"file": "x.py", "old": "1", "new": "2"}]

    def test_empty_on_invalid(self):
        assert _parse_patch("this is not json at all") == []

    def test_empty_changes_list(self):
        raw = json.dumps({"changes": [], "explanation": "nothing"})
        assert _parse_patch(raw) == []

    def test_multiple_changes(self):
        raw = json.dumps({
            "changes": [
                {"file": "a.py", "old": "1", "new": "2"},
                {"file": "b.py", "old": "3", "new": "4"},
            ]
        })
        result = _parse_patch(raw)
        assert len(result) == 2
        assert result[1]["file"] == "b.py"


# ── _apply_changes ────────────────────────────────────────────────────────────

class TestApplyChanges:
    def test_edit_existing_file(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("x = 1\n", encoding="utf-8")
        changes = [{"file": "hello.py", "old": "x = 1\n", "new": "x = 2\n"}]
        result = _apply_changes(changes, str(tmp_path))
        assert len(result) == 1
        assert "_error" not in result[0]
        assert f.read_text("utf-8") == "x = 2\n"

    def test_write_new_file(self, tmp_path):
        changes = [{"file": "new.py", "old": "", "new": "y = 99\n"}]
        result = _apply_changes(changes, str(tmp_path))
        assert "_error" not in result[0]
        assert (tmp_path / "new.py").read_text("utf-8") == "y = 99\n"

    def test_edit_nonexistent_records_error(self, tmp_path):
        changes = [{"file": "ghost.py", "old": "nope", "new": "yes"}]
        result = _apply_changes(changes, str(tmp_path))
        assert "_error" in result[0]

    def test_multi_file_changes(self, tmp_path):
        (tmp_path / "a.py").write_text("val = 1\n")
        (tmp_path / "b.py").write_text("val = 2\n")
        changes = [
            {"file": "a.py", "old": "val = 1\n", "new": "val = 10\n"},
            {"file": "b.py", "old": "val = 2\n", "new": "val = 20\n"},
        ]
        result = _apply_changes(changes, str(tmp_path))
        assert all("_error" not in r for r in result)
        assert (tmp_path / "a.py").read_text("utf-8") == "val = 10\n"
        assert (tmp_path / "b.py").read_text("utf-8") == "val = 20\n"


# ── _build_patch_messages ────────────────────────────────────────────────────

class TestBuildMessages:
    def test_includes_task(self, tmp_path):
        (tmp_path / "foo.py").write_text("def foo(): pass\n")
        located = [{"rel": "foo.py", "score": 5, "reason": "符号", "symbols_matched": ["foo"]}]
        msgs = _build_patch_messages("修复 foo 函数", located, str(tmp_path))
        user_content = msgs[1]["content"]
        assert "修复 foo 函数" in user_content
        assert "foo.py" in user_content

    def test_includes_file_content(self, tmp_path):
        (tmp_path / "bar.py").write_text("x = 42\n")
        located = [{"rel": "bar.py", "score": 3, "reason": "", "symbols_matched": []}]
        msgs = _build_patch_messages("fix bar", located, str(tmp_path))
        assert "x = 42" in msgs[1]["content"]

    def test_system_is_first(self, tmp_path):
        msgs = _build_patch_messages("task", [], str(tmp_path))
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    def test_repair_messages_include_failure(self):
        msgs = _build_repair_messages(
            "fix bug",
            [{"file": "a.py", "old": "x", "new": "y"}],
            "AssertionError: expected 1 got 2",
            1,
        )
        user = msgs[1]["content"]
        assert "AssertionError" in user
        assert "a.py" in user
        assert "第 1 轮" in user


# ── AgentlessPipeline ────────────────────────────────────────────────────────

def _fake_pipeline(api_key="k", base_url="http://x", model_id="m",
                   max_repair_rounds=2) -> AgentlessPipeline:
    return AgentlessPipeline(api_key, base_url, model_id, max_repair_rounds)


class TestPipelineNoFiles:
    def test_no_files_returns_no_files_status(self, tmp_path):
        pipeline = _fake_pipeline()
        with patch("agentless_pipeline.locate_relevant", return_value=[]):
            result = asyncio.run(pipeline.run("fix something", str(tmp_path)))
        assert result.status == "no_files"
        assert result.located_files == []


class TestPipelineSuccess:
    def test_success_first_try(self, tmp_path):
        """Patch 成功 → 验证立即通过 → completed。"""
        src = tmp_path / "math.py"
        src.write_text("def add(a, b): return a - b\n")

        patch_json = json.dumps({
            "changes": [{"file": "math.py",
                         "old": "def add(a, b): return a - b\n",
                         "new": "def add(a, b): return a + b\n"}],
        })

        fake_locate = [{"rel": "math.py", "score": 5, "reason": "符号命中", "symbols_matched": ["add"]}]
        fake_vr = {"ok": True, "ran": True, "command": "pytest", "kind": "pytest",
                   "exit_code": 0, "failure_summary": ""}

        pipeline = _fake_pipeline()
        with patch("agentless_pipeline.locate_relevant", return_value=fake_locate), \
             patch("agentless_pipeline._chat_once", new_callable=AsyncMock,
                   return_value=patch_json), \
             patch("agentless_pipeline.run_verification", return_value=fake_vr):
            result = asyncio.run(pipeline.run("fix add function", str(tmp_path)))

        assert result.status == "completed"
        assert result.rounds == 1
        assert "math.py" in result.located_files
        assert src.read_text("utf-8") == "def add(a, b): return a + b\n"

    def test_success_after_repair(self, tmp_path):
        """第一轮失败 → 修复轮成功 → completed。"""
        src = tmp_path / "calc.py"
        src.write_text("x = 1\n")

        first_patch = json.dumps({"changes": [{"file": "calc.py", "old": "x = 1\n", "new": "x = 0\n"}]})
        repair_patch = json.dumps({"changes": [{"file": "calc.py", "old": "x = 0\n", "new": "x = 2\n"}]})

        vr_fail = {"ok": False, "ran": True, "command": "pytest", "kind": "pytest",
                   "exit_code": 1, "failure_summary": "AssertionError", "stdout": "FAILED", "stderr": ""}
        vr_ok = {"ok": True, "ran": True, "command": "pytest", "kind": "pytest",
                 "exit_code": 0, "failure_summary": "", "stdout": "", "stderr": ""}

        fake_locate = [{"rel": "calc.py", "score": 3, "reason": "", "symbols_matched": []}]
        call_count = [0]

        async def fake_chat(msgs, *a, **kw):
            call_count[0] += 1
            return first_patch if call_count[0] == 1 else repair_patch

        vr_seq = [vr_fail, vr_ok]
        vr_idx = [0]

        def fake_vr(root, cmd=None):
            r = vr_seq[vr_idx[0]]
            vr_idx[0] = min(vr_idx[0] + 1, len(vr_seq) - 1)
            return r

        pipeline = _fake_pipeline(max_repair_rounds=2)
        with patch("agentless_pipeline.locate_relevant", return_value=fake_locate), \
             patch("agentless_pipeline._chat_once", side_effect=fake_chat), \
             patch("agentless_pipeline.run_verification", side_effect=fake_vr):
            result = asyncio.run(pipeline.run("fix calc", str(tmp_path)))

        assert result.status == "completed"
        assert result.rounds == 2

    def test_unverified_after_max_rounds(self, tmp_path):
        """所有修复轮都失败 → unverified。"""
        src = tmp_path / "broken.py"
        src.write_text("x = 1\n")

        patch_json = json.dumps({"changes": [{"file": "broken.py", "old": "x = 1\n", "new": "x = 0\n"}]})
        vr_fail = {"ok": False, "ran": True, "command": "pytest", "kind": "pytest",
                   "exit_code": 1, "failure_summary": "AssertionError",
                   "stdout": "FAILED broken", "stderr": ""}

        fake_locate = [{"rel": "broken.py", "score": 2, "reason": "", "symbols_matched": []}]
        pipeline = _fake_pipeline(max_repair_rounds=1)

        with patch("agentless_pipeline.locate_relevant", return_value=fake_locate), \
             patch("agentless_pipeline._chat_once", new_callable=AsyncMock,
                   return_value=patch_json), \
             patch("agentless_pipeline.run_verification", return_value=vr_fail):
            result = asyncio.run(pipeline.run("fix broken", str(tmp_path)))

        assert result.status == "unverified"
        assert len(result.changes_applied) >= 1

    def test_llm_failure_returns_failed_status(self, tmp_path):
        fake_locate = [{"rel": "x.py", "score": 1, "reason": "", "symbols_matched": []}]
        (tmp_path / "x.py").write_text("pass\n")
        pipeline = _fake_pipeline()

        async def raise_conn(*a, **kw):
            raise ConnectionError("network down")

        with patch("agentless_pipeline.locate_relevant", return_value=fake_locate), \
             patch("agentless_pipeline._chat_once", side_effect=raise_conn):
            result = asyncio.run(pipeline.run("fix x", str(tmp_path)))

        assert result.status == "failed"
        assert "network down" in result.error

    def test_invalid_patch_json_returns_failed(self, tmp_path):
        (tmp_path / "y.py").write_text("pass\n")
        fake_locate = [{"rel": "y.py", "score": 1, "reason": "", "symbols_matched": []}]
        pipeline = _fake_pipeline()

        with patch("agentless_pipeline.locate_relevant", return_value=fake_locate), \
             patch("agentless_pipeline._chat_once", new_callable=AsyncMock,
                   return_value="I cannot help with that."):
            result = asyncio.run(pipeline.run("fix y", str(tmp_path)))

        assert result.status == "failed"

    def test_result_to_dict(self):
        r = PipelineResult(status="completed", summary="ok", rounds=1, located_files=["a.py"])
        d = r.to_dict()
        assert d["status"] == "completed"
        assert d["located_files"] == ["a.py"]


# ── Executor 路由 ─────────────────────────────────────────────────────────────

class TestAgentlessRouting:
    def test_parse_agentless_prefix(self):
        from executor_worker import _parse_agentless_prefix
        is_ag, task = _parse_agentless_prefix("agentless: fix the bug")
        assert is_ag is True
        assert task == "fix the bug"

    def test_parse_agentless_prefix_chinese_colon(self):
        from executor_worker import _parse_agentless_prefix
        is_ag, task = _parse_agentless_prefix("Agentless：修复报错")
        assert is_ag is True
        assert task == "修复报错"

    def test_no_agentless_prefix(self):
        from executor_worker import _parse_agentless_prefix
        is_ag, task = _parse_agentless_prefix("fix the bug normally")
        assert is_ag is False
        assert task == "fix the bug normally"

    def test_agentless_prefix_case_insensitive(self):
        from executor_worker import _parse_agentless_prefix
        is_ag, _ = _parse_agentless_prefix("AGENTLESS: task")
        assert is_ag is True
