#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
harness_evolution — Harness 自演化提案（v1.3.1 Phase P2）

命题（AHE，arXiv:2604.25850）：把模型固定，让 harness 的工具 / 中间件 / 长期记忆随真实
失败数据演化，增益来自这些组件的演化、而非 prompt 措辞。本模块就是这条闭环的"读数 → 提案"段：

  失败记忆（R）累计"哪类错误反复撞"，解法记忆（P3）累计"哪类被解决过"。两者共用同一套
  错误签名（error_signature），天然可配对。本模块读这两份数据，按证据生成**排序的 harness
  改进提案**：

    · 高频 + 从未解决  → 高优先级：最该长一个**前置检查工具 / 中间件**，在出错前拦住，
                          而不是每次靠模型盲目重试。
    · 高频 + 已可解    → 中优先级：把**已知解法固化成工具 / 代码片段**，免模型每次重新推导。

  让真实失败数据告诉你 harness 该往哪长，而不是拍脑袋堆功能（v1.3 的反"特性军备竞赛"原则）。

安全边界：本模块**只读 + 产出建议**，绝不自动改代码 / 改配置——harness 演化是高风险动作，
人审后再落地。它是仪表盘，不是自动驾驶。

CLI：`python -m harness_evolution`（读进程级失败 / 解法记忆，打印 markdown 提案表）。
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional

# 优先级排序权重（数值越小越靠前）
_PRIO_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Proposal:
    signature: str
    category: str
    failure_count: int
    resolved_count: int
    priority: str          # high / medium / low
    lever: str             # 该往哪长：tool/middleware｜memory/snippet
    rationale: str         # 为什么这么建议
    sample: str = ""       # 首次记录的错误样子（节选）

    def to_dict(self) -> dict:
        return asdict(self)


def analyze(failure_mem, solution_mem, *, min_count: int = 3) -> list[Proposal]:
    """读失败 + 解法记忆，产出排序的 harness 改进提案。

    failure_mem / solution_mem 是任何带 .all() 的对象（FailureMemory / SolutionMemory，
    或测试里的桩）——不硬依赖单例，便于离线测试。
    """
    fails: dict = failure_mem.all() if failure_mem else {}
    sols: dict = solution_mem.all() if solution_mem else {}

    proposals: list[Proposal] = []
    for sig, f in fails.items():
        count = int(f.get("count", 0) or 0)
        if count < min_count:
            continue
        s = sols.get(sig)
        resolved = int(s.get("resolved_count", 0) or 0) if s else 0
        if resolved == 0:
            priority, lever = "high", "tool/middleware"
            rationale = (
                f"高频未解错误类（已撞 {count} 次、从未被解决）——最该长一个前置检查工具或"
                f"中间件，在出错前拦住，而不是每次靠模型重试。")
        else:
            priority, lever = "medium", "memory/snippet"
            rmin = int(s.get("rounds_min") or 0)
            fast = f"、最快 {rmin} 轮修好" if rmin else ""
            rationale = (
                f"高频但可解（撞 {count} 次、已解决 {resolved} 次{fast}）——候选把已知解法"
                f"固化成工具 / 代码片段，免模型每次重新推导。")
        proposals.append(Proposal(
            signature=sig,
            category=str(f.get("category", "")),
            failure_count=count,
            resolved_count=resolved,
            priority=priority,
            lever=lever,
            rationale=rationale,
            sample=(f.get("summary") or "").strip().splitlines()[0][:120]
                   if f.get("summary") else "",
        ))

    # 高优先级在前；同级按撞击次数降序（越痛越靠前）
    proposals.sort(key=lambda p: (_PRIO_ORDER.get(p.priority, 9), -p.failure_count))
    return proposals


def format_report(proposals: list[Proposal], *,
                  fail_total: int = 0, sol_total: int = 0, min_count: int = 3) -> str:
    """把提案渲染成 markdown 表。"""
    lines = [
        "# Harness 自演化提案",
        "",
        f"> 数据源：{fail_total} 条失败记忆 / {sol_total} 条解法记忆，阈值 = 撞 ≥ {min_count} 次。",
        f"> 依据 AHE（arXiv:2604.25850）：让真实失败数据决定 harness 该长什么工具 / 中间件 / 记忆。",
        "> 本表只建议、不自动改代码——人审后落地。",
        "",
    ]
    if not proposals:
        lines.append("**暂无达到阈值的反复失败**——当前 harness 没有被数据点名的短板，"
                     "别为保险堆功能。继续用 eval 完成率盯着，等数据说话。")
        return "\n".join(lines)

    _icon = {"high": "🔴 高", "medium": "🟡 中", "low": "⚪ 低"}
    lines += [
        "| 优先级 | 杠杆 | 撞 | 解 | 错误类 | 建议 |",
        "|---|---|---|---|---|---|",
    ]
    for p in proposals:
        cls = p.sample or p.category or p.signature
        lines.append(
            f"| {_icon.get(p.priority, p.priority)} | {p.lever} | {p.failure_count} "
            f"| {p.resolved_count} | {cls[:48]} | {p.rationale} |")
    return "\n".join(lines)


def main(min_count: int = 3) -> str:
    """CLI 入口：读进程级失败 / 解法记忆，返回 markdown 报告。"""
    from failure_memory import get_failure_memory
    from solution_memory import get_solution_memory
    fm = get_failure_memory()
    sm = get_solution_memory()
    props = analyze(fm, sm, min_count=min_count)
    return format_report(props, fail_total=len(fm.all()),
                         sol_total=len(sm.all()), min_count=min_count)


if __name__ == "__main__":
    import sys
    try:                                  # Windows 控制台默认 GBK，emoji 会崩
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    mc = 3
    if len(sys.argv) > 1:
        try:
            mc = int(sys.argv[1])
        except ValueError:
            pass
    print(main(min_count=mc))
