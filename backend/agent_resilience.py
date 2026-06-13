#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentResilienceMixin — 循环级错误恢复（H6）
从 agent_base.py 抽出，独立维护。

三道保险：
  1. 重复失败熔断：同一工具调用连续失败 3 次注入提示，5 次强制拦截
  2. API 故障退避：429/5xx 指数退避重试（最多 3 次）
  3. 输出截断续写：finish_reason == "length" → 追加"继续"（最多 2 次）

由 AgentBase 继承；依赖 self._log, self._call_api。
"""
import asyncio
import hashlib
import json


_PARALLEL_SAFE = frozenset({
    "file_read", "list_dir", "search_code", "glob_files",
    "find_symbol", "find_usages", "git_status", "git_diff",
    "git_log", "web_search", "fetch_url", "map_project",
})


class AgentResilienceMixin:
    """循环级错误恢复 + 并行工具执行 Mixin，供 AgentBase 继承。"""

    @staticmethod
    def _tool_hash(name: str, args: dict) -> str:
        raw = name + json.dumps(args, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    @staticmethod
    def _check_breaker(name: str, args: dict, fail_counts: dict) -> dict | None:
        """熔断检查。返回 None=放行，返回 dict=拦截（作为工具结果）。"""
        h = AgentResilienceMixin._tool_hash(name, args)
        count = fail_counts.get(h, 0)
        if count >= 5:
            return {"error": f"工具 {name} 同参数已连续失败 {count} 次，已强制拦截。换一种方法或 ask_user。"}
        if count >= 3:
            return {"error": f"工具 {name} 同参数已连续失败 {count} 次，请换一种方法，或用 ask_user 告诉用户。",
                    "_breaker_warning": True}
        return None

    @staticmethod
    def _record_tool_result(name: str, args: dict, result: dict, fail_counts: dict):
        """记录工具调用结果，更新熔断计数。"""
        h = AgentResilienceMixin._tool_hash(name, args)
        if "error" in result:
            fail_counts[h] = fail_counts.get(h, 0) + 1
        else:
            fail_counts.pop(h, None)

    async def _call_api_resilient(self, messages, tools=None, stream=True,
                                  override_model=None, on_delta=None,
                                  session_id="", turn=0) -> dict:
        """_call_api 包装：429/5xx 指数退避重试 + truncation 续写。"""
        delays = [2, 8, 30]
        last_resp = None
        for attempt in range(len(delays) + 1):
            resp = await self._call_api(messages, tools=tools, stream=stream,
                                        override_model=override_model, on_delta=on_delta)
            if "error" not in resp:
                last_resp = resp
                break
            err = resp.get("error", "")
            status = 0
            if err.startswith("API "):
                try:
                    status = int(err.split(":")[0].split()[-1])
                except (ValueError, IndexError):
                    pass
            if status in (429, 500, 502, 503) and attempt < len(delays):
                self._log(session_id, "api_retry", {
                    "turn": turn, "attempt": attempt + 1, "status": status})
                await asyncio.sleep(delays[attempt])
                continue
            return resp
        if last_resp is None:
            return {"error": "API 重试耗尽"}
        return last_resp

    async def _execute_tools_maybe_parallel(
        self, tool_calls: list[dict], fail_counts: dict, ctx: dict | None,
    ) -> list[tuple[str, dict, dict]]:
        """H5: 解析 tool_calls → 执行（只读全量并行 / 否则串行）→ [(name, args, result)]。"""
        parsed = []
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}
                parsed.append((tc, name, args, {"error": f"参数解析失败: {tc['function']['arguments'][:200]}"}))
                continue
            breaker = self._check_breaker(name, args, fail_counts)
            if breaker is not None:
                parsed.append((tc, name, args, breaker))
                continue
            parsed.append((tc, name, args, None))

        need_exec = [(i, n, a) for i, (_, n, a, r) in enumerate(parsed) if r is None]
        can_parallel = (len(need_exec) > 1 and
                        all(n in _PARALLEL_SAFE for _, n, _ in need_exec))

        if can_parallel:
            coros = [self._execute_tool(n, a, ctx=ctx) for _, n, a in need_exec]
            results = await asyncio.gather(*coros)
            for (idx, _, _), res in zip(need_exec, results):
                tc_orig, name, args, _ = parsed[idx]
                parsed[idx] = (tc_orig, name, args, res)
        else:
            for idx, name, args in need_exec:
                res = await self._execute_tool(name, args, ctx=ctx)
                tc_orig = parsed[idx][0]
                parsed[idx] = (tc_orig, name, args, res)

        for _, name, args, result in parsed:
            if result is not None:
                self._record_tool_result(name, args, result, fail_counts)
        return [(tc, name, args, result) for tc, name, args, result in parsed]
