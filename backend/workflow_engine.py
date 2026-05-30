#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workflow_engine.py — 工作流执行引擎（M10 Part 2-4）

把原来散在 routes/workflow.py 里的执行逻辑抽成一个**可复用、可流式、可单测**的
引擎，并补齐"更强节点"：

  节点类型
    sequential  顺序（叶子）         —— 支持 retry / timeout / on_error
    parallel    并行多分支           —— 每个分支独立 retry/timeout
    condition   条件分支             —— keyword 直配 **或** mode="ai" 让模型判定
    router      多路路由（AI 选路）   —— 模型在多个 label 里挑最匹配的一条
    loop        循环                 —— max_iter + stop_keyword
    human       人审闸门             —— 暂停、问用户、approve/reject 决定走停
    taozu       陶朱动态节点          —— 运行时把一句话目标编译成子图再执行

  设计要点
    - 一个 `emit(event)` 异步回调把每步进展实时吐出去（流式执行/实时回显）。
      不传 emit 就是静默批处理（旧 /workflow/run 行为不变）。
    - 一个 `gate(step_idx, message)` 异步回调实现人审：返回
      {"action":"approve"|"reject","note":str}。不传 gate（纯批处理）时
      人审节点**默认放行**并标注 auto_approved，保证非交互场景不死锁。
    - `generator`（有 async _call_api 的对象）供 AI 路由 / 陶朱动态展开使用。
    - 纯逻辑，靠注入 servers/generator/gate 即可不触网单测。

engine 不关心传输层：HTTP 一次性 POST、WebSocket 流式、定时任务都能复用它。
"""
from __future__ import annotations

import asyncio
import time as _time
from typing import Awaitable, Callable, Optional


# emit 事件名（仅文档用途；前端按 event 字段分发）
EV_START   = "start"
EV_STEP    = "step_start"
EV_RETRY   = "step_retry"
EV_DONE    = "step_done"
EV_GATE    = "human_gate"
EV_ROUTE   = "router_decision"
EV_EXPAND  = "taozu_expanded"
EV_FINISH  = "done"
EV_ERROR   = "error"


def _coerce_output(result) -> str:
    if isinstance(result, dict):
        return result.get("summary") or result.get("content") or str(result)
    return str(result)


class WorkflowRunner:
    def __init__(self, servers, *,
                 emit: Optional[Callable[[dict], Awaitable]] = None,
                 use_kb: bool = False,
                 kb=None,
                 generator=None,
                 gate: Optional[Callable[[int, str], Awaitable[dict]]] = None,
                 max_dynamic_depth: int = 2):
        self.servers = servers
        self.emit_cb = emit
        self.use_kb = use_kb
        self.kb = kb
        self.generator = generator
        self.gate = gate
        self.max_dynamic_depth = max_dynamic_depth
        self.stopped = False          # on_error=stop / 人审 reject 后置位
        self.stop_reason = ""

    # ── 事件 ──────────────────────────────────────────────────────────────
    async def _emit(self, event: str, **kw):
        if self.emit_cb:
            try:
                await self.emit_cb({"event": event, **kw})
            except Exception:
                pass  # 回显失败不该拖垮执行

    # ── 叶子执行（含 retry / timeout / on_error）───────────────────────────
    async def _exec_leaf(self, step_def: dict, step_idx: int, ctx: str) -> dict:
        agent_id = step_def.get("agent", "xi")
        prompt   = (step_def.get("prompt") or "").strip()
        pass_ctx = step_def.get("pass_context", True)
        retry    = max(0, int(step_def.get("retry", 0) or 0))
        timeout  = step_def.get("timeout")
        timeout  = float(timeout) if timeout else None
        on_error = step_def.get("on_error", "continue")

        if not prompt:
            return {"step": step_idx, "agent": agent_id, "type": "sequential",
                    "output": "(跳过：提示词为空)", "elapsed": 0, "ok": True}

        srv = self.servers.get(agent_id)
        if not srv:
            out = f"错误：未知 agent {agent_id}"
            if on_error == "stop":
                self.stopped = True
                self.stop_reason = out
            return {"step": step_idx, "agent": agent_id, "type": "sequential",
                    "output": out, "elapsed": 0, "ok": False, "error": out}

        full_prompt = prompt
        if pass_ctx and ctx:
            full_prompt = f"【上一步输出】\n{ctx}\n\n【当前任务】\n{prompt}"
        if self.use_kb and self.kb is not None:
            try:
                kb_ctx = await asyncio.to_thread(self.kb.build_context, prompt, 3)
                if kb_ctx:
                    full_prompt = kb_ctx + "\n\n" + full_prompt
            except Exception:
                pass

        t0 = _time.time()
        last_err = None
        for attempt in range(retry + 1):
            try:
                coro = srv.worker.run(full_prompt)
                result = await (asyncio.wait_for(coro, timeout) if timeout else coro)
                elapsed = round(_time.time() - t0, 1)
                return {"step": step_idx, "agent": agent_id, "type": "sequential",
                        "output": _coerce_output(result), "elapsed": elapsed,
                        "prompt": prompt, "ok": True,
                        "attempts": attempt + 1}
            except asyncio.TimeoutError:
                last_err = f"超时（>{timeout}s）"
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
            if attempt < retry:
                await self._emit(EV_RETRY, step=step_idx, agent=agent_id,
                                 attempt=attempt + 1, error=last_err)

        elapsed = round(_time.time() - t0, 1)
        out = f"执行错误: {last_err}"
        if on_error == "stop":
            self.stopped = True
            self.stop_reason = out
        return {"step": step_idx, "agent": agent_id, "type": "sequential",
                "output": out, "elapsed": elapsed, "ok": False,
                "error": last_err, "attempts": retry + 1}

    # ── AI 判定：在 labels 里挑一个最匹配 content 的 ──────────────────────
    async def _ai_pick(self, criterion: str, content: str, labels: list[str]) -> Optional[str]:
        if self.generator is None:
            return None
        opts = "、".join(labels)
        sys = ("你是一个分类器。根据【内容】判断它属于哪一类，"
               f"只能从这些选项里选一个并原样输出该选项，不要解释：{opts}。\n"
               f"判定标准：{criterion}")
        msgs = [{"role": "system", "content": sys},
                {"role": "user", "content": f"【内容】\n{content[:4000]}"}]
        try:
            resp = await self.generator._call_api(msgs, tools=None, stream=False)
        except Exception:
            return None
        if not isinstance(resp, dict) or resp.get("error"):
            return None
        ans = (resp.get("content") or "").strip()
        # 先找完全包含的 label，再退回首个出现的
        for lb in labels:
            if lb and lb in ans:
                return lb
        return None

    # ── 节点：condition ───────────────────────────────────────────────────
    async def _run_condition(self, step: dict, i: int, prev: str) -> dict:
        keyword  = step.get("keyword", "")
        mode     = step.get("mode", "keyword")
        true_s   = step.get("true_step")
        false_s  = step.get("false_step")

        if mode == "ai":
            criterion = step.get("question") or keyword or "内容是否满足条件"
            picked = await self._ai_pick(criterion, prev, ["是", "否"])
            matched = (picked == "是")
            decided_by = "ai"
        else:
            matched = keyword.lower() in prev.lower() if keyword else False
            decided_by = "keyword"

        await self._emit(EV_ROUTE, step=i, kind="condition",
                         matched=matched, by=decided_by, keyword=keyword)
        chosen = true_s if matched else false_s
        if not chosen:
            return {"step": i, "type": "condition", "matched": matched,
                    "by": decided_by, "elapsed": 0,
                    "output": f"(条件 '{keyword}' {'满足' if matched else '不满足'}，无对应分支)"}
        r = await self._exec_leaf(chosen, i, prev)
        r["type"] = "condition"
        r["keyword"] = keyword
        r["matched"] = matched
        r["by"] = decided_by
        return r

    # ── 节点：router（多路 AI 选路）──────────────────────────────────────
    async def _run_router(self, step: dict, i: int, prev: str) -> dict:
        routes   = step.get("routes") or []
        question = step.get("question") or step.get("keyword") or "内容最匹配哪一类"
        valid    = [r for r in routes if isinstance(r, dict) and isinstance(r.get("step"), dict)]
        if not valid:
            return {"step": i, "type": "router", "elapsed": 0,
                    "output": "(路由节点无有效分支)"}
        labels = [str(r.get("label") or f"路线{k+1}") for k, r in enumerate(valid)]
        picked = await self._ai_pick(question, prev, labels)
        if picked is None:
            picked = labels[0]  # 兜底走第一条，绝不卡死
        idx = labels.index(picked)
        await self._emit(EV_ROUTE, step=i, kind="router", chosen=picked,
                         options=labels)
        r = await self._exec_leaf(valid[idx]["step"], i, prev)
        r["type"] = "router"
        r["chosen"] = picked
        r["options"] = labels
        return r

    # ── 节点：human（人审闸门）──────────────────────────────────────────
    async def _run_human(self, step: dict, i: int, prev: str) -> dict:
        message = step.get("message") or step.get("prompt") or "请审核上一步的产出，决定是否继续。"
        await self._emit(EV_GATE, step=i, message=message, preview=prev[:1200])
        if self.gate is None:
            # 非交互（批处理）默认放行，避免死锁
            return {"step": i, "type": "human", "elapsed": 0,
                    "action": "approve", "auto_approved": True,
                    "output": prev or "(已自动通过人工审核)"}
        try:
            decision = await self.gate(i, message)
        except Exception as e:  # noqa: BLE001
            decision = {"action": "approve", "note": f"(人审回调异常，默认放行: {e})"}
        action = (decision or {}).get("action", "approve")
        note   = (decision or {}).get("note", "")
        if action == "reject":
            self.stopped = True
            self.stop_reason = note or "用户在人审节点终止了工作流"
            return {"step": i, "type": "human", "elapsed": 0,
                    "action": "reject", "note": note,
                    "output": f"⛔ 已被人工终止：{note or '(未填原因)'}"}
        return {"step": i, "type": "human", "elapsed": 0,
                "action": "approve", "note": note,
                # 用户填了 note 就把它当作注入下游的新上下文，否则透传 prev
                "output": note or prev or "(已通过人工审核)"}

    # ── 节点：taozu（运行时编译子图并执行）──────────────────────────────
    async def _run_taozu(self, step: dict, i: int, prev: str, depth: int) -> dict:
        goal = (step.get("goal") or step.get("prompt") or "").strip()
        if not goal:
            return {"step": i, "type": "taozu", "elapsed": 0,
                    "output": "(陶朱节点缺少 goal)"}
        if self.generator is None or depth >= self.max_dynamic_depth:
            return {"step": i, "type": "taozu", "elapsed": 0,
                    "output": "(陶朱动态展开不可用：无规划器或超出展开深度)"}
        from workflow_ai import ai_build_workflow
        # 把上一步产出并入目标，让陶朱据此规划
        plan_goal = goal if not prev else f"{goal}\n\n（可参考的上一步产出）：\n{prev[:2000]}"
        t0 = _time.time()
        built = await ai_build_workflow(self.generator, plan_goal)
        if not built.get("ok"):
            return {"step": i, "type": "taozu", "elapsed": round(_time.time()-t0, 1),
                    "output": f"(陶朱规划失败：{built.get('error','未知')})"}
        sub_steps = built["steps"]
        await self._emit(EV_EXPAND, step=i, name=built.get("name"),
                         sub_count=len(sub_steps),
                         explanation=built.get("explanation", ""))
        sub_results, sub_prev = await self._run_steps(sub_steps, prev, depth + 1,
                                                      step_prefix=f"{i}.")
        return {"step": i, "type": "taozu", "name": built.get("name"),
                "explanation": built.get("explanation", ""),
                "elapsed": round(_time.time() - t0, 1),
                "output": sub_prev, "sub_results": sub_results}

    # ── 节点：parallel ───────────────────────────────────────────────────
    async def _run_parallel(self, step: dict, i: int, prev: str) -> dict:
        branches = step.get("branches", [])
        if not branches:
            return {"step": i, "type": "parallel", "elapsed": 0,
                    "output": "(并行节点无分支)"}
        t0 = _time.time()
        tasks = [self._exec_leaf(b, i, prev) for b in branches]
        branch_results = await asyncio.gather(*tasks, return_exceptions=True)
        outputs, clean = [], []
        for br in branch_results:
            if isinstance(br, dict):
                outputs.append(f"[{br.get('agent','?')}] {br.get('output','')}")
                clean.append(br)
            elif isinstance(br, Exception):
                outputs.append(f"[错误] {br}")
        combined = "\n\n---\n\n".join(outputs)
        return {"step": i, "type": "parallel", "output": combined,
                "elapsed": round(_time.time() - t0, 1), "branches": clean}

    # ── 节点：loop ───────────────────────────────────────────────────────
    async def _run_loop(self, step: dict, i: int, prev: str) -> dict:
        max_iter   = max(1, int(step.get("max_iter", 3) or 3))
        stop_word  = step.get("stop_keyword", "完成")
        inner_step = step.get("step")
        if not isinstance(inner_step, dict):
            return {"step": i, "type": "loop", "elapsed": 0,
                    "output": "(循环节点缺少 step 定义)"}
        t0 = _time.time()
        loop_output, iteration = prev, 0
        for iteration in range(max_iter):
            r = await self._exec_leaf(inner_step, i, loop_output)
            loop_output = r["output"]
            if self.stopped:
                break
            if stop_word and stop_word.lower() in loop_output.lower():
                break
        return {"step": i, "type": "loop", "output": loop_output,
                "elapsed": round(_time.time() - t0, 1), "iterations": iteration + 1}

    # ── 跑一串步骤（顶层与陶朱子图共用）──────────────────────────────────
    async def _run_steps(self, steps: list, prev: str, depth: int = 0,
                         step_prefix: str = "") -> tuple[list, str]:
        results = []
        for idx, step in enumerate(steps, start=1):
            if self.stopped:
                break
            node_type = step.get("type", "sequential")
            label = f"{step_prefix}{idx}"
            await self._emit(EV_STEP, step=label, type=node_type,
                             agent=step.get("agent"))
            if node_type == "parallel":
                r = await self._run_parallel(step, label, prev)
            elif node_type == "condition":
                r = await self._run_condition(step, label, prev)
            elif node_type == "router":
                r = await self._run_router(step, label, prev)
            elif node_type == "loop":
                r = await self._run_loop(step, label, prev)
            elif node_type == "human":
                r = await self._run_human(step, label, prev)
            elif node_type == "taozu":
                r = await self._run_taozu(step, label, prev, depth)
            else:
                r = await self._exec_leaf(step, label, prev)
                r["type"] = "sequential"
            prev = r.get("output", prev)
            results.append(r)
            await self._emit(EV_DONE, step=label, type=r.get("type"),
                             output=r.get("output", ""),
                             elapsed=r.get("elapsed", 0), ok=r.get("ok", True),
                             extra={k: r[k] for k in
                                    ("matched", "chosen", "action", "iterations",
                                     "attempts", "sub_count", "name")
                                    if k in r})
        return results, prev

    # ── 对外入口 ─────────────────────────────────────────────────────────
    async def run(self, steps: list) -> dict:
        if not steps:
            return {"ok": False, "error": "steps 为空", "results": []}
        await self._emit(EV_START, total=len(steps))
        try:
            results, _ = await self._run_steps(steps, "")
        except asyncio.CancelledError:
            await self._emit(EV_ERROR, message="已取消")
            raise
        except Exception as e:  # noqa: BLE001
            await self._emit(EV_ERROR, message=str(e))
            return {"ok": False, "error": str(e), "results": []}
        out = {"ok": True, "results": results,
               "stopped": self.stopped, "stop_reason": self.stop_reason}
        await self._emit(EV_FINISH, results=results, stopped=self.stopped,
                         stop_reason=self.stop_reason)
        return out


async def run_workflow(steps, servers, **kw) -> dict:
    """便捷入口：构造 WorkflowRunner 并执行。"""
    return await WorkflowRunner(servers, **kw).run(steps)
