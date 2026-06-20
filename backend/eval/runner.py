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


_TRANSIENT_NAMES = frozenset({
    "ClientConnectorError", "ClientOSError", "ServerDisconnectedError",
    "ServerTimeoutError", "ClientResponseError", "ConnectionError",
    "TimeoutError", "OSError",
})


def _classify_error(exc: Exception) -> str:
    """把 solver 抛的异常分三类：

      "setup"     — 环境/配置/权限缺失（PermissionRequest）。对每道题都一样 → 整套中止，
                    不算进完成率。
      "transient" — 瞬态网络/超时（ClientConnectorError、TimeoutError 等）。solver 连 API
                    都没摸到，不是模型能力问题 → 不算进完成率，但不中止整套（下一题可能通了）。
      "crash"     — 真正的 solver 逻辑崩溃 → 算该题失败，不中止整套。

    用类名判断而非 isinstance，避免 eval 包硬依赖 aiohttp / agent_base（保持离线可测）。"""
    name = type(exc).__name__
    if name == "PermissionRequest":
        return "setup"
    if name in _TRANSIENT_NAMES:
        return "transient"
    for base in type(exc).__mro__:
        if base.__name__ in _TRANSIENT_NAMES:
            return "transient"
    return "crash"


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
    error_kind: str = ""          # ""=正常 / "setup"=配置坑 / "transient"=网络抖动 / "crash"=偶发崩 / "skipped"=整套中止

    @property
    def attempted(self) -> bool:
        """这道题是否真正被「跑过」。没跑过的不计入能力度量：
        - setup: 配置坑，agent 没起跑
        - skipped: 整套中止后被跳过
        - transient: 网络/超时，solver 连 API 都没摸到
        crash 算跑过（solver 真起来了只是崩了）。"""
        return self.error_kind not in ("setup", "skipped", "transient")


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
    def attempted_count(self) -> int:
        """真正起跑的题数（排除 setup / transient / skipped）。"""
        return sum(1 for r in self.results if r.attempted)

    @property
    def completion_rate(self) -> float:
        """自主完成率 = 通过题数 / 总题数（含未起跑的）。原始数。"""
        return (self.passed / self.total) if self.total else 0.0

    @property
    def attempted_rate(self) -> float:
        """真实能力完成率 = 通过题数 / 真正起跑的题数。排除了网络/配置噪声后的干净数。
        有未起跑的题时，这个数才是可信的能力度量；全部起跑时与 completion_rate 一致。"""
        return (self.passed / self.attempted_count) if self.attempted_count else 0.0

    @property
    def not_attempted(self) -> int:
        """没真正起跑的题数（setup / transient / skipped）。> 0 时 completion_rate 被噪声污染。"""
        return sum(1 for r in self.results if not r.attempted)

    @property
    def reliable(self) -> bool:
        """整套是否可信：所有题都真正起跑过，没有环境/配置/网络错误把题挡在门外。
        不可信时 completion_rate 度量的是基础设施，不是模型能力——看 attempted_rate 更准。"""
        return self.total > 0 and self.not_attempted == 0

    def setup_reasons(self) -> list[str]:
        """去重后的 setup/transient 错误原因（用于报告里告诉用户「该修什么」）。"""
        seen, out = set(), []
        for r in self.results:
            if r.error_kind in ("setup", "transient") and r.error and r.error not in seen:
                seen.add(r.error)
                out.append(r.error)
        return out

    def to_dict(self) -> dict:
        return {
            "model": self.model, "label": self.label,
            "total": self.total, "passed": self.passed,
            "attempted": self.attempted_count,
            "completion_rate": round(self.completion_rate, 4),
            "attempted_rate": round(self.attempted_rate, 4),
            "not_attempted": self.not_attempted,
            "reliable": self.reliable,
            "started_at": self.started_at,
            "results": [asdict(r) for r in self.results],
        }


def _write_files(files: dict[str, str], workspace: Path) -> None:
    for rel, content in files.items():
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def materialize(task: EvalTask, workspace: Path) -> None:
    """把任务的初始文件写进工作区。"""
    _write_files(task.setup_files, workspace)


def apply_solution(task: EvalTask, workspace: Path) -> None:
    """把参考解覆盖进工作区。配合 grade 做「这题确实可解」的离线纪律检查——
    保证一道题既「初始即红」（test_seed_task_starts_red）又「参考解能转绿」，
    两侧夹住，避免发布一道根本做不出的题、让 harness 背锅。"""
    _write_files(task.solution_files, workspace)


def grade(task: EvalTask, workspace: Path) -> dict:
    """跑验收命令，复用 verify_gate 的结构化结果。返回 {ok, exit_code, failure_summary,...}。"""
    return run_verification(str(workspace), command=_resolve_command(task.verify),
                            timeout=task.timeout)


async def run_task(task: EvalTask, solver: Solver, model: str | None = None,
                   keep_workspace: bool = False) -> TaskResult:
    """跑单题：物化 → solver 改 → 验收。solver 异常不致命，记为该题失败。"""
    workspace = Path(tempfile.mkdtemp(prefix=f"eval_{task.id}_"))
    t0 = time.time()
    status, rounds, err, err_kind = "", 0, "", ""
    try:
        materialize(task, workspace)
        try:
            agent_out = await solver(task.prompt, workspace, model)
            if isinstance(agent_out, dict):
                status = str(agent_out.get("status", ""))
                rounds = int(agent_out.get("turn_count", 0) or 0)
        except Exception as e:  # solver 崩了 = 这题没做成，但不能拖垮整套
            err = f"solver 异常: {type(e).__name__}: {e}"
            err_kind = _classify_error(e)
        verdict = grade(task, workspace)
        return TaskResult(
            id=task.id,
            passed=bool(verdict.get("ok")) and not err,
            exit_code=verdict.get("exit_code"),
            rounds=rounds,
            elapsed=round(time.time() - t0, 2),
            status=err_kind or status,
            failure_summary="" if verdict.get("ok") else str(verdict.get("failure_summary", ""))[:500],
            error=err,
            error_kind=err_kind,
        )
    finally:
        if not keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)


async def run_suite(tasks: list[EvalTask], solver: Solver, model: str | None = None,
                    label: str = "") -> SuiteResult:
    """串行跑全套（题之间隔离，串行避免互相抢资源/污染度量）。

    系统性环境错误（setup，如未配 relay_url）会让每道题都同样失败 → 一旦撞上就整套中止：
    剩余题标 skipped 不再起跑。这既避免刷一屏相同的假失败，也避免对真实模型白烧额度。"""
    suite = SuiteResult(model=model or "(default)", label=label)
    aborted_reason = ""
    for task in tasks:
        if aborted_reason:
            suite.results.append(TaskResult(
                id=task.id, passed=False, exit_code=None,
                status="skipped", error_kind="skipped",
                error=f"已跳过：整套因环境错误中止（{aborted_reason}）"))
            continue
        res = await run_task(task, solver, model)
        suite.results.append(res)
        if res.error_kind == "setup":
            aborted_reason = res.error
    return suite


# ── 生产 solver：真正驱动 executor agent（需 API Key，烧额度）─────────────────
def make_executor_solver(verify_gate: bool = True,
                         max_repair_rounds: int | None = None) -> Solver:
    """构造真实 solver：每题起一个 executor，工作区根目录 = 隔离 workspace。

    这是 E4「跑基线」实际用的 solver，需配置好模型 API Key。本函数只构造，
    不在 import 期触网；真正花额度发生在 run_suite 调用时。

    `verify_gate` 是消融开关：同一模型、同一套题，开/关 Verify 闸门各跑一次，
    `format_compare(off, on)` 的完成率差 = 闸门对弱模型的真实增益（v1.3 的核心论点
    「厚 harness 让弱模型变强」就靠这个差值证伪/证真，而非凭感觉）。
    """
    async def _solve(prompt: str, workspace: Path, model: str | None) -> dict:
        from executor_worker import ExecutorWorker
        worker = ExecutorWorker()
        # 把 agent 的文件操作根钉在隔离工作区，并通过 project 注入上下文
        worker.work_dir = workspace
        worker.verify_gate = verify_gate          # 消融：关掉它，看弱模型会不会「没测就收工」
        if max_repair_rounds is not None:
            worker.max_repair_rounds = max_repair_rounds
        task = (f"工作目录就是当前项目根：{workspace}\n"
                f"所有文件路径相对它。完成后必须让验收测试通过。\n\n{prompt}")
        return await worker.run(task, model=model, project=str(workspace))
    return _solve


def default_tasks() -> list[EvalTask]:
    return load_tasks()
