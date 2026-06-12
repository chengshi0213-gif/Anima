#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_executor_worker.py — v1.2.2 A2 项目记忆注入 + 路径作用域规则单元测试 (pytest)

覆盖：
  - ExecutorWorker.run() 把 load_project_memory() 的结果拼进首条任务文本
  - file_read/file_edit 命中 .anima/rules/*.md 时结果带 scoped_rule

不触网：monkeypatch 掉 AgentBase.run，只验证 ExecutorWorker.run 自己做的预处理。

运行:
    cd E:\\AI\\workspace\\Anima\\backend
    python -m pytest tests/test_executor_worker.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import executor_worker as ew  # noqa: E402
import project_memory as pm  # noqa: E402
from agent_base import AgentBase  # noqa: E402


@pytest.fixture
def worker(monkeypatch, tmp_path):
    """构造 ExecutorWorker，并把它的日志/工作区指到临时目录。"""
    monkeypatch.setattr(ew, "LOG_DIR", tmp_path / "logs", raising=False)
    w = ew.ExecutorWorker()
    w.log_dir = tmp_path / "logs"
    w.work_dir = tmp_path / "work"
    w.log_dir.mkdir(parents=True, exist_ok=True)
    w.work_dir.mkdir(parents=True, exist_ok=True)
    w._notes_dir = w.work_dir / "notes"
    w._notes_dir.mkdir(parents=True, exist_ok=True)
    return w


def _capture_super_run(monkeypatch, captured: dict):
    async def fake_run(self, task, session_id=None, model=None, ws=None, project=None):
        captured["task"] = task
        captured["project"] = project
        return {"status": "completed", "summary": "ok",
                "files_changed": [], "turn_count": 1}
    monkeypatch.setattr(AgentBase, "run", fake_run)


def test_project_memory_injected_into_task(worker, monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "ANIMA.md").write_text("项目规范：用 pytest -x 跑测试", encoding="utf-8")

    captured: dict = {}
    _capture_super_run(monkeypatch, captured)

    out = asyncio.run(worker.run("修个 bug", project=str(proj)))

    assert out["status"] == "completed"
    assert "项目规范：用 pytest -x 跑测试" in captured["task"]
    assert worker._current_project_root == str(proj)


def test_no_project_memory_section_when_nothing_to_load(worker, monkeypatch, tmp_path):
    proj = tmp_path / "empty_proj"
    proj.mkdir()

    captured: dict = {}
    _capture_super_run(monkeypatch, captured)

    asyncio.run(worker.run("做点什么", project=str(proj)))
    assert "# 项目记忆（自动注入）" not in captured["task"]


def test_scoped_rule_attached_on_file_read_and_edit(worker, tmp_path):
    proj = tmp_path / "proj"
    rules = proj / ".anima" / "rules"
    rules.mkdir(parents=True)
    (rules / "testing.md").write_text(
        "---\npaths: [\"**/*.test.py\"]\n---\n测试文件必须 mock 网络请求",
        encoding="utf-8",
    )

    target = proj / "src" / "app.test.py"
    target.parent.mkdir(parents=True)
    target.write_text("print('hi')", encoding="utf-8")

    worker._current_project_root = str(proj)

    read_result = worker.tool_dispatch["file_read"](path=str(target))
    assert "mock 网络请求" in read_result.get("scoped_rule", "")

    edit_result = worker.tool_dispatch["file_edit"](
        path=str(target), old_string="hi", new_string="bye",
    )
    assert "mock 网络请求" in edit_result.get("scoped_rule", "")


def test_no_scoped_rule_for_unmatched_file(worker, tmp_path):
    proj = tmp_path / "proj"
    rules = proj / ".anima" / "rules"
    rules.mkdir(parents=True)
    (rules / "testing.md").write_text(
        "---\npaths: [\"**/*.test.py\"]\n---\n测试文件必须 mock 网络请求",
        encoding="utf-8",
    )

    target = proj / "src" / "util.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1", encoding="utf-8")

    worker._current_project_root = str(proj)

    read_result = worker.tool_dispatch["file_read"](path=str(target))
    assert "scoped_rule" not in read_result


# ════════════════════════════════════════════════════════════════════
#  A4 — Auto Memory
# ════════════════════════════════════════════════════════════════════

def test_save_auto_memory_writes_when_useful(worker, monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()

    async def fake_call_api(messages, tools=None, stream=False, override_model=None, on_delta=None):
        return {"content": "测试命令：pytest -x --tb=short"}
    monkeypatch.setattr(worker, "_call_api", fake_call_api)

    asyncio.run(worker._save_auto_memory(
        "sess1", "修个bug", {"summary": "修好了", "files_changed": ["a.py"]}, str(proj)))

    assert "测试命令：pytest -x --tb=short" in pm.read_auto_memory(str(proj))


def test_save_auto_memory_skips_when_no_value(worker, monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()

    async def fake_call_api(messages, tools=None, stream=False, override_model=None, on_delta=None):
        return {"content": "无"}
    monkeypatch.setattr(worker, "_call_api", fake_call_api)

    asyncio.run(worker._save_auto_memory(
        "sess1", "修个bug", {"summary": "修好了", "files_changed": ["a.py"]}, str(proj)))

    assert pm.read_auto_memory(str(proj)) == ""


def test_save_auto_memory_skips_on_api_error(worker, monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()

    async def fake_call_api(*a, **k):
        return {"error": "boom"}
    monkeypatch.setattr(worker, "_call_api", fake_call_api)

    asyncio.run(worker._save_auto_memory(
        "sess1", "修个bug", {"summary": "x", "files_changed": ["a.py"]}, str(proj)))

    assert pm.read_auto_memory(str(proj)) == ""


def test_run_triggers_auto_memory_when_completed_with_files(worker, monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()

    async def fake_run(self, task, session_id=None, model=None, ws=None, project=None):
        return {"status": "completed", "summary": "done",
                "files_changed": ["a.py"], "turn_count": 1}
    monkeypatch.setattr(AgentBase, "run", fake_run)

    created = []
    def fake_create_task(coro):
        created.append(coro)
        coro.close()
        return None
    monkeypatch.setattr(ew.asyncio, "create_task", fake_create_task)

    asyncio.run(worker.run("task", project=str(proj)))
    assert len(created) == 1


def test_run_skips_auto_memory_when_no_files_changed(worker, monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()

    async def fake_run(self, task, session_id=None, model=None, ws=None, project=None):
        return {"status": "completed", "summary": "done",
                "files_changed": [], "turn_count": 1}
    monkeypatch.setattr(AgentBase, "run", fake_run)

    created = []
    def fake_create_task(coro):
        created.append(coro)
        coro.close()
        return None
    monkeypatch.setattr(ew.asyncio, "create_task", fake_create_task)

    asyncio.run(worker.run("task", project=str(proj)))
    assert len(created) == 0


def test_run_skips_auto_memory_when_no_project(worker, monkeypatch):
    async def fake_run(self, task, session_id=None, model=None, ws=None, project=None):
        return {"status": "completed", "summary": "done",
                "files_changed": ["a.py"], "turn_count": 1}
    monkeypatch.setattr(AgentBase, "run", fake_run)

    created = []
    def fake_create_task(coro):
        created.append(coro)
        coro.close()
        return None
    monkeypatch.setattr(ew.asyncio, "create_task", fake_create_task)

    asyncio.run(worker.run("task", project=None))
    assert len(created) == 0


# ════════════════════════════════════════════════════════════════════
#  C1 — ask_user 工具
# ════════════════════════════════════════════════════════════════════

def test_ask_user_no_ws(worker):
    result = asyncio.run(worker._ask_user("选哪个？"))
    assert result["answer"] is None
    assert "error" in result


def test_ask_user_receives_answer(worker):
    sent = []
    class FakeWS:
        async def send_json(self, data):
            sent.append(data)

    worker._current_ws = FakeWS()

    async def _test():
        async def _answer_later():
            await asyncio.sleep(0.05)
            worker.receive_user_answer("选B")
        asyncio.create_task(_answer_later())
        return await worker._ask_user("选A还是B？", ["选A", "选B"])

    result = asyncio.run(_test())
    assert result["answer"] == "选B"
    assert result["timed_out"] is False
    assert sent[0]["type"] == "ask_user"
    assert sent[0]["question"] == "选A还是B？"


def test_ask_user_timeout_returns_first_choice(worker):
    sent = []
    class FakeWS:
        async def send_json(self, data):
            sent.append(data)

    worker._current_ws = FakeWS()
    result = asyncio.run(worker._ask_user("选？", ["默认选项"], timeout=0.1))
    assert result["timed_out"] is True
    assert result["answer"] == "默认选项"


def test_ask_user_timeout_no_choices(worker):
    class FakeWS:
        async def send_json(self, data): pass

    worker._current_ws = FakeWS()
    result = asyncio.run(worker._ask_user("问？", timeout=0.1))
    assert result["timed_out"] is True
    assert result["answer"] is None


def test_receive_user_answer_sets_event(worker):
    worker._ask_event = asyncio.Event()
    worker.receive_user_answer("hello")
    assert worker._ask_answer == "hello"
    assert worker._ask_event.is_set()


def test_run_stores_ws(worker, monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()

    async def fake_run(self, task, session_id=None, model=None, ws=None, project=None):
        return {"status": "completed", "summary": "done",
                "files_changed": [], "turn_count": 1}
    monkeypatch.setattr(AgentBase, "run", fake_run)

    fake_ws = object()
    asyncio.run(worker.run("task", ws=fake_ws, project=str(proj)))
    assert worker._current_ws is fake_ws
