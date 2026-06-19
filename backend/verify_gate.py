#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_gate — Plan-Execute-Verify 闸门（v1.3 Phase V）

核心命题（2026 harness 研究 + Fable 5 复盘）：
  弱模型最缺的不是推理，是"改完自动验证 → 结构化报错回灌 → 自修复到绿"的反馈闭环。
  二元 pass/fail 远不如"带上下文的错误消息"有用。

本模块只做三件纯粹的事，不持有 agent 状态：
  1. detect_verify_command(root)  探测项目该怎么验证（pytest / npm test / tsc / cargo / go）
  2. looks_like_verify(command)   判断模型自己跑的某条 shell 是不是"验证"（用于免重复跑闸门）
  3. run_verification(root, cmd)   跑验证 → 结构化结果（含失败摘要，给模型回灌用）

不依赖 AgentBase；run_verification 复用 xi_worker._shell_run（已有危险命令闸门）。
"""
from __future__ import annotations
import re
from pathlib import Path


# ── 各语言的探测规则：(标志文件存在性判定, 验证命令, 类别) ─────────────────
# 顺序即优先级：先命中的先用。
def detect_verify_command(project_root: str | None) -> tuple[str, str] | None:
    """探测项目的验证命令。返回 (command, kind)，探测不到返回 None。

    kind ∈ {pytest, npm, tsc, cargo, gotest}，仅用于日志/展示。
    纯文件系统判断，不执行任何命令，可安全频繁调用（建议调用方缓存）。
    """
    if not project_root:
        return None
    root = Path(project_root)
    if not root.is_dir():
        return None

    # Python：有 tests 目录或常见配置 → pytest
    has_py_cfg = any((root / f).exists() for f in (
        "pytest.ini", "pyproject.toml", "setup.py", "setup.cfg", "tox.ini"))
    has_tests_dir = (root / "tests").is_dir() or (root / "test").is_dir()
    if has_tests_dir or has_py_cfg:
        # 有 tests 目录优先；否则退回配置（仍跑 pytest，让它自己发现）
        return ("pytest -q", "pytest")

    # Node：package.json 决定走 npm test 还是 tsc
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            text = pkg.read_text("utf-8", errors="replace")
            if re.search(r'"test"\s*:', text):
                return ("npm test --silent", "npm")
        except OSError:
            pass
        if (root / "tsconfig.json").is_file():
            return ("npx tsc --noEmit", "tsc")
        return ("npm test --silent", "npm")

    if (root / "tsconfig.json").is_file():
        return ("npx tsc --noEmit", "tsc")

    # Rust
    if (root / "Cargo.toml").is_file():
        return ("cargo test --quiet", "cargo")

    # Go
    if (root / "go.mod").is_file():
        return ("go test ./...", "gotest")

    return None


# 模型自己跑的命令里，长这样的算"验证动作"——闸门据此免重复跑。
_VERIFY_PATTERNS = re.compile(
    r"\b("
    r"pytest|py\.test|unittest|nose2"
    r"|npm\s+(run\s+)?test|yarn\s+test|pnpm\s+test|jest|vitest|mocha"
    r"|tsc\b|tsc\s+--noEmit"
    r"|cargo\s+test|go\s+test"
    r"|mypy|ruff\s+check|flake8|eslint|pylint"
    r"|make\s+(test|check)"
    r")\b",
    re.IGNORECASE,
)


def looks_like_verify(command: str) -> bool:
    """这条 shell 命令是不是一次"验证"（测试/类型检查/lint）。"""
    if not command:
        return False
    return bool(_VERIFY_PATTERNS.search(command))


# ── 失败摘要提炼：从 pytest / tsc / 通用输出里抠出最有用的几行 ──────────────
_PYTEST_FAIL = re.compile(r"^(FAILED|ERROR)\s+\S+", re.MULTILINE)
_ASSERT_LINE = re.compile(r"^E\s+.*$", re.MULTILINE)        # pytest 的 E 开头断言行
_TSC_ERROR = re.compile(r"^.*error TS\d+:.*$", re.MULTILINE)
_GENERIC_ERR = re.compile(
    r"^.*(Error|Exception|assert|Assertion|Traceback|panic:).*$",
    re.MULTILINE | re.IGNORECASE)


def summarize_failure(stdout: str, stderr: str, max_lines: int = 25) -> str:
    """从验证输出里提炼关键失败信息，供回灌给模型。

    优先级：pytest FAILED 行 + E 断言行 > tsc error 行 > 通用 Error/Traceback 行。
    抠不到结构化信号时，回退给 stderr/stdout 的尾部（最后的输出往往最相关）。
    """
    combined = (stdout or "") + "\n" + (stderr or "")
    picked: list[str] = []

    for rx in (_PYTEST_FAIL, _ASSERT_LINE, _TSC_ERROR):
        for m in rx.finditer(combined):
            line = m.group(0).rstrip()
            if line and line not in picked:
                picked.append(line)

    if not picked:
        for m in _GENERIC_ERR.finditer(combined):
            line = m.group(0).rstrip()
            if line and line not in picked:
                picked.append(line)

    if not picked:
        # 完全没有可识别信号 → 给输出尾部
        tail = (stderr or stdout or "").strip().splitlines()[-max_lines:]
        return "\n".join(tail)

    return "\n".join(picked[:max_lines])


def run_verification(project_root: str | None, command: str | None = None,
                     timeout: int = 180) -> dict:
    """跑一次验证，返回结构化结果。

    返回字段：
      ok            bool   exit_code == 0
      ran           bool   是否真的执行了（探测不到命令时 False）
      command       str    实际跑的命令
      kind          str    验证类别
      exit_code     int
      failure_summary str  失败时的关键错误（ok=True 时为空）
    """
    if command is None:
        detected = detect_verify_command(project_root)
        if detected is None:
            return {"ok": False, "ran": False, "command": "",
                    "kind": "", "exit_code": -1, "failure_summary": "",
                    "note": "未探测到可用的验证命令（无 tests/ 或已知项目配置）"}
        command, kind = detected
    else:
        det = detect_verify_command(project_root)
        kind = det[1] if det else "custom"

    # 复用 xi_worker 的 shell_run（带危险命令闸门 + 编码处理）
    from xi_worker import _shell_run
    result = _shell_run(command, timeout=timeout, cwd=project_root or ".")

    if "error" in result and "exit_code" not in result:
        # shell 层错误（如被安全策略拒绝）
        return {"ok": False, "ran": False, "command": command, "kind": kind,
                "exit_code": -1, "failure_summary": result["error"],
                "note": result["error"]}

    exit_code = result.get("exit_code", -1)
    ok = exit_code == 0
    summary = "" if ok else summarize_failure(
        result.get("stdout", ""), result.get("stderr", ""))
    return {"ok": ok, "ran": True, "command": command, "kind": kind,
            "exit_code": exit_code, "failure_summary": summary}


def format_repair_message(result: dict, round_no: int, max_rounds: int) -> str:
    """把验证失败结构化成一条 user 消息，回灌给模型自修复。

    研究依据（Augment PEV）：反馈必须是带上下文的错误，不是二元 pass/fail。
    """
    cmd = result.get("command", "验证命令")
    code = result.get("exit_code", "?")
    detail = result.get("failure_summary") or "（无结构化错误输出，请自行复跑排查）"
    return (
        f"[自动验证闸门] 你声称完成，但验证未通过——还不能收工。\n"
        f"验证命令：`{cmd}`（exit_code={code}）\n"
        f"第 {round_no}/{max_rounds} 轮修复。关键错误：\n"
        f"```\n{detail}\n```\n"
        f"请定位根因、修复，**改完务必再亲自跑一遍 `{cmd}` 确认 exit_code=0**，"
        f"全绿之前不要说完成。"
    )
