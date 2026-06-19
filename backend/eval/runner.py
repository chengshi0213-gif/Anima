#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval.runner — 对指定模型跑全任务集

流程（每道题）：
  1. 开一个隔离临时工作区（mkdtemp）
  2. 物化 setup.files
  3. 调 solver(prompt, workspace, model) 让 agent 在工作区里改文件
  4. 跑 verify 验收命令（复用 verify_gate.run_verification → exit 0 = 通过）
  5. 记录 通过/退出码/轮数/耗时

度量与执行解耦：solver 是注入的 → 框架离线可测（stub solver 不触网）。
真正烧 API 的"跑 DeepSeek 基线"用 make_executor_solver()（见 __main__.py），
由用户一键触发，本模块默认不替用户花额度。
"""
from __future__ import annotations
import asyncio, shutil, sys, tempfile, time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Awaitable, Callable

from verify_gate import run_verification

from .spec import EvalTask, load_tasks


def _resolve_command(command: str) -> str:
    """把 verify 命令里的 {py} 占位符换成当前解释器（带引号）。

    任务 yaml 里写 `{py} -m pytest -q` 而非裸 `python`/`pytest`——后者依赖 PATH，
    在用户机器（解释器是 C:\\Python314\\python.exe，未必在 PATH）上会让所有题误判为红、
    污染基线。占位符保证可移植。"""
    return command.replace("{py}", f'"{sys.executable}"')

# solver 协议：给一句任务描述 + 工作区路径 + 模型名，让 agent 干活。
# 返回 agent 的结果 dict（含 turn_count / status 等，用于统计；评分只认 verify）。
Solver = Callable[[str, Path, str | None], Awaitable[dict]]


@dataclass
class TaskResult:
    id: str
    passed: bool
    exit_code: int | None
    rounds: int = 0
    elapsed: float = 0.0
    status: str = ""              # agent 自报状态（completed/unverified/error...）
    failure_summary: str = ""     # 验收失败摘要（红时）
    error: str = ""               # 跑题过程异常（solver 抛错等）


@dataclass
class SuiteResult:
    model: str
    label: str = ""               # 这次跑的标签（如 "baseline" / "with-verify-gate"）
    results: list[TaskResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def completion_rate(self) -> float:
        """自主完成率 = 通过题数 / 总题数。核心数。"""
        return (self.passed / self.total) if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "model": self.model, "label": self.label,
            "total": self.total, "passed": self.passed,
            "completion_rate": round(self.completion_rate, 4),
            "started_at": self.started_at,
            "results": [asdict(r) for r in self.results],
        }


def materialize(task: EvalTask, workspace: Path) -> None:
    """把任务的初始文件写进工作区。"""
    for rel, content in task.setup_files.items():
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def grade(task: EvalTask, workspace: Path) -> dict:
    """跑验收命令，复用 verify_gate 的结构化结果。返回 {ok, exit_code, failure_summary,...}。"""
    return run_verification(str(workspace), command=_resolve_command(task.verify),
                            timeout=task.timeout)


async def run_task(task: EvalTask, solver: Solver, model: str | None = None,
                   keep_workspace: bool = False) -> TaskResult:
    """跑单题：物化 → solver 改 → 验收。solver 异常不致命，记为该题失败。"""
    workspace = Path(tempfile.mkdtemp(prefix=f"eval_{task.id}_"))
    t0 = time.time()
    status, rounds, err = "", 0, ""
    try:
        materialize(task, workspace)
        try:
            agent_out = await solver(task.prompt, workspace, model)
            if isinstance(agent_out, dict):
                status = str(agent_out.get("status", ""))
                rounds = int(agent_out.get("turn_count", 0) or 0)
        except Exception as e:  # solver 崩了 = 这题没做成，但不能拖垮整套
            err = f"solver 异常: {type(e).__name__}: {e}"
        verdict = grade(task, workspace)
        return TaskResult(
            id=task.id,
            passed=bool(verdict.get("ok")) and not err,
            exit_code=verdict.get("exit_code"),
            rounds=rounds,
            elapsed=round(time.time() - t0, 2),
            status=status,
            failure_summary="" if verdict.get("ok") else str(verdict.get("failure_summary", ""))[:500],
            error=err,
        )
    finally:
        if not keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)


async def run_suite(tasks: list[EvalTask], solver: Solver, model: str | None = None,
                    label: str = "") -> SuiteResult:
    """串行跑全套（题之间隔离，串行避免互相抢资源/污染度量）。"""
    suite = SuiteResult(model=model or "(default)", label=label)
    for task in tasks:
        suite.results.append(await run_task(task, solver, model))
    return suite


# ── 生产 solver：真正驱动 executor agent（需 API Key，烧额度）─────────────────
def make_executor_solver() -> Solver:
    """构造真实 solver：每题起一个 executor，工作区根目录 = 隔离 workspace。

    这是 E4「跑基线」实际用的 solver，需配置好模型 API Key。本函数只构造，
    不在 import 期触网；真正花额度发生在 run_suite 调用时。
    """
    async def _solve(prompt: str, workspace: Path, model: str | None) -> dict:
        from executor_worker import ExecutorWorker
        worker = ExecutorWorker()
        # 把 agent 的文件操作根钉在隔离工作区，并通过 project 注入上下文
        worker.work_dir = workspace
        task = (f"工作目录就是当前项目根：{workspace}\n"
                f"所有文件路径相对它。完成后必须让验收测试通过。\n\n{prompt}")
        return await worker.run(task, model=model, project=str(workspace))
    return _solve


def default_tasks() -> list[EvalTask]:
    return load_tasks()
