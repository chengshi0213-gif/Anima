#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E (v1.3) 评估脊柱测试：spec 加载校验 + runner 隔离跑 + report 报告。

全部离线：solver 用 stub，不触网、不烧 API。验收命令用当前解释器跑（{py} 占位符），
所以"真实 pytest 评分通路"也被覆盖到，只是被测对象是临时微工作区里的玩具代码。
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.spec import EvalTask, load_task, load_tasks, TASKS_DIR
from eval.runner import (
    materialize, grade, run_task, run_suite, _resolve_command, TaskResult, SuiteResult,
)
from eval.report import format_report, format_compare, save_report


# ── stub solvers（不触网）────────────────────────────────────────────────────
async def _noop_solver(prompt, workspace, model):
    """什么都不改的 agent → 题目应保持红。"""
    return {"status": "completed", "turn_count": 1}


def _fix_solver_for(filename: str, content: str):
    async def _solve(prompt, workspace, model):
        (Path(workspace) / filename).write_text(content, encoding="utf-8")
        return {"status": "completed", "turn_count": 2}
    return _solve


# 轻量任务：验收用 `{py} -c "import done"`，避开 pytest 启动开销，跑 suite/report 测试用
def _light_task(tid: str) -> EvalTask:
    return EvalTask(id=tid, prompt=f"创建 done.py（{tid}）",
                    verify='{py} -c "import done"')


_DONE_SOLVER = _fix_solver_for("done.py", "# marker\n")


# ── spec ─────────────────────────────────────────────────────────────────────
def test_load_real_task():
    t = load_task(TASKS_DIR / "bugfix-off-by-one.yaml")
    assert t.id == "bugfix-off-by-one"
    assert "mathutil.py" in t.setup_files
    assert t.verify.strip()


def test_reject_bad_id():
    with pytest.raises(ValueError):
        EvalTask(id="Bad ID!", prompt="x", verify="y")


def test_reject_missing_prompt():
    with pytest.raises(ValueError):
        EvalTask(id="ok", prompt="   ", verify="y")


def test_reject_missing_verify():
    with pytest.raises(ValueError):
        EvalTask(id="ok", prompt="do", verify="")


def test_title_defaults_to_id():
    assert EvalTask(id="abc", prompt="p", verify="v").title == "abc"


def test_load_tasks_seed_set():
    tasks = load_tasks()
    assert len(tasks) >= 6                       # 种子集至少 6 道
    ids = [t.id for t in tasks]
    assert len(ids) == len(set(ids))             # id 唯一
    assert ids == sorted(ids)                     # 排序稳定


@pytest.mark.parametrize("task", load_tasks(), ids=lambda t: t.id)
def test_seed_task_starts_red(task, tmp_path):
    """纪律闸门：每道发布的题，初始状态（未改）跑验收必须是红。
    否则"什么都不做"也能过 = 这题没判别力，会让基线数字虚高。"""
    materialize(task, tmp_path)
    assert grade(task, tmp_path)["ok"] is False, f"{task.id} 初始竟然是绿的——失去判别力"


# ── runner：物化 + 评分 ───────────────────────────────────────────────────────
def test_materialize_writes_files(tmp_path):
    t = _light_task("mat")
    t.setup_files = {"a.py": "x = 1\n", "sub/b.txt": "hi"}
    materialize(t, tmp_path)
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert (tmp_path / "sub" / "b.txt").read_text(encoding="utf-8") == "hi"


def test_resolve_command_substitutes_interpreter():
    out = _resolve_command("{py} -m pytest -q")
    assert "{py}" not in out
    assert sys.executable in out


def test_grade_red_then_green(tmp_path):
    t = _light_task("rg")
    materialize(t, tmp_path)
    assert grade(t, tmp_path)["ok"] is False     # 没有 done.py → 红
    (tmp_path / "done.py").write_text("# x\n", encoding="utf-8")
    assert grade(t, tmp_path)["ok"] is True       # 有了 → 绿


# ── runner：跑单题（用真实种子题，覆盖真实 pytest 评分通路）───────────────────
def test_run_task_noop_fails_real_pytest():
    t = load_task(TASKS_DIR / "bugfix-off-by-one.yaml")
    res = asyncio.run(run_task(t, _noop_solver))
    assert isinstance(res, TaskResult)
    assert res.passed is False                    # 初始即红，什么都不改 → 不过
    assert res.failure_summary                     # 有结构化失败摘要


def test_run_task_fix_passes_real_pytest():
    t = load_task(TASKS_DIR / "bugfix-off-by-one.yaml")
    fix = _fix_solver_for("mathutil.py", "def sum_to(n):\n    return sum(range(n + 1))\n")
    res = asyncio.run(run_task(t, fix))
    assert res.passed is True
    assert res.exit_code == 0
    assert res.rounds == 2                         # solver 自报轮数透传


def test_run_task_solver_crash_is_not_fatal():
    async def _boom(prompt, ws, model):
        raise RuntimeError("solver 炸了")
    t = _light_task("boom")
    res = asyncio.run(run_task(t, _boom))
    assert res.passed is False
    assert "solver 异常" in res.error
    assert res.error_kind == "crash"          # 偶发崩 = 这一题的事
    assert res.attempted is True              # solver 真起来了，算跑过


# ── setup 错（环境/配置坑）：不能伪装成 0% 基线 ──────────────────────────────
class _FakePermissionRequest(Exception):
    """模拟 agent_base.PermissionRequest（按类名分类，无需真依赖 agent_base）。"""
    pass
_FakePermissionRequest.__name__ = "PermissionRequest"


def test_run_task_setup_error_marked_not_attempted():
    async def _needs_config(prompt, ws, model):
        raise _FakePermissionRequest("需要权限: 中转服务地址")
    res = asyncio.run(run_task(_light_task("cfg"), _needs_config))
    assert res.error_kind == "setup"
    assert res.attempted is False             # 没起跑 → 不计入能力


def test_run_suite_aborts_on_setup_error():
    """第一题撞环境错 → 整套中止，剩余题 skipped 不再起跑（不白烧额度）。"""
    calls = []

    async def _solver(prompt, ws, model):
        calls.append(prompt)
        raise _FakePermissionRequest("需要权限: 中转服务地址")
    tasks = [_light_task("a1"), _light_task("a2"), _light_task("a3")]
    suite = asyncio.run(run_suite(tasks, _solver, model="Claude-Sonnet-4.6"))
    assert len(calls) == 1                    # 只跑了第一题，其余被跳过
    assert suite.results[0].error_kind == "setup"
    assert suite.results[1].error_kind == "skipped"
    assert suite.results[2].error_kind == "skipped"
    assert suite.reliable is False
    assert suite.not_attempted == 3
    assert suite.setup_reasons() == ["solver 异常: PermissionRequest: 需要权限: 中转服务地址"]


def test_run_suite_crash_does_not_abort():
    """单题偶发崩 ≠ 系统性环境错 → 不中止整套，后续题照跑。"""
    seen = []

    async def _solver(prompt, ws, model):
        seen.append(prompt)
        if "c1" in prompt:
            raise RuntimeError("就这题崩了")
        (Path(ws) / "done.py").write_text("# x\n", encoding="utf-8")
        return {"status": "completed", "turn_count": 1}
    tasks = [_light_task("c1"), _light_task("c2"), _light_task("c3")]
    suite = asyncio.run(run_suite(tasks, _solver))
    assert len(seen) == 3                      # 全跑了，没中止
    assert suite.passed == 2                    # c2/c3 过
    assert suite.reliable is True               # crash 不影响可信性


def test_run_task_cleans_workspace(tmp_path, monkeypatch):
    created = {}
    real_mkdtemp = __import__("tempfile").mkdtemp

    def _spy(*a, **k):
        p = real_mkdtemp(*a, **k)
        created["path"] = p
        return p
    monkeypatch.setattr("eval.runner.tempfile.mkdtemp", _spy)
    asyncio.run(run_task(_light_task("clean"), _DONE_SOLVER))
    assert not Path(created["path"]).exists()      # 默认清理临时工作区


# ── runner：跑整套 + 完成率 ──────────────────────────────────────────────────
def test_run_suite_completion_rate():
    tasks = [_light_task("s1"), _light_task("s2"), _light_task("s3")]
    # solver 只在 s1/s2 创建 done.py，s3 留空 → 期望 2/3
    async def _selective(prompt, ws, model):
        if "s3" not in prompt:
            (Path(ws) / "done.py").write_text("# x\n", encoding="utf-8")
        return {"status": "completed", "turn_count": 1}
    suite = asyncio.run(run_suite(tasks, _selective, model="StubModel", label="t"))
    assert suite.total == 3
    assert suite.passed == 2
    assert abs(suite.completion_rate - 2 / 3) < 1e-9
    assert suite.model == "StubModel"


# ── report ───────────────────────────────────────────────────────────────────
def _fake_suite(model, label, passed_ids, failed_ids) -> SuiteResult:
    s = SuiteResult(model=model, label=label)
    for i in passed_ids:
        s.results.append(TaskResult(id=i, passed=True, exit_code=0, rounds=1))
    for i in failed_ids:
        s.results.append(TaskResult(id=i, passed=False, exit_code=1, rounds=3))
    return s


def test_format_report_has_rate_and_ids():
    s = _fake_suite("M", "base", ["a", "b"], ["c"])
    out = format_report(s)
    assert "66.7%" in out
    for i in ("a", "b", "c"):
        assert i in out


def test_format_compare_shows_delta_and_fixed():
    a = _fake_suite("DeepSeek", "before", ["a"], ["b", "c"])     # 1/3
    b = _fake_suite("DeepSeek", "after", ["a", "b"], ["c"])       # 2/3
    out = format_compare(a, b, "before", "after")
    assert "修好了" in out                          # b 这题从红转绿
    assert "＋" in out                               # 完成率上升


def test_save_report_writes_md_and_json(tmp_path):
    s = _fake_suite("M", "base", ["a"], ["b"])
    p = save_report(s, tmp_path / "r" / "out.md")
    assert p.exists()
    assert p.with_suffix(".json").exists()
    assert "50.0%" in p.read_text(encoding="utf-8")


def _setup_errored_suite() -> SuiteResult:
    """模拟 E4 实际撞到的情形：全部题因未配 relay_url 没起跑。"""
    s = SuiteResult(model="Claude-Sonnet-4.6", label="claude-ref")
    s.results.append(TaskResult(id="t1", passed=False, exit_code=1,
                                error="solver 异常: PermissionRequest: 需要权限: 中转服务地址",
                                error_kind="setup"))
    s.results.append(TaskResult(id="t2", passed=False, exit_code=None,
                                error="已跳过：整套因环境错误中止", error_kind="skipped"))
    return s


def test_report_flags_unreliable_baseline():
    out = format_report(_setup_errored_suite())
    assert "此基线不可信" in out                  # 醒目警告
    assert "中转服务地址" in out                   # 告诉用户修什么
    assert "⚠" in out and "⏭" in out             # setup / skipped 标记区分


def test_reliable_suite_has_no_banner():
    out = format_report(_fake_suite("M", "ok", ["a", "b"], ["c"]))
    assert "不可信" not in out                     # 正常基线不该有警告


def test_compare_warns_when_a_side_unreliable():
    bad = _setup_errored_suite()
    good = _fake_suite("DeepSeek", "baseline", ["t1"], ["t2"])
    out = format_compare(good, bad, "deepseek", "claude-ref")
    assert "对比无效" in out
