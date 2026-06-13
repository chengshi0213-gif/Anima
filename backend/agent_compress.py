#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentCompressMixin — 历史压缩、异步落盘摘要、上次摘要扫描
从 agent_base.py 抽出，独立维护。

由 AgentBase 继承；依赖 self 上的以下属性：
  self._notes_dir, self._compress_semaphore, self._call_api,
  self._log, self.name, self.coding_compress
"""
import asyncio, hashlib, json, re
from datetime import datetime


_STRUCTURED_PROMPT = """\
请根据以下对话历史生成结构化摘要（八段式，每段2-3句，总计800字内）。

{history}

按以下格式输出（不要遗漏任何段）：
1. 原始任务：用户最初要什么（逐字保留核心要求）
2. 技术决策：选了什么方案、为什么
3. 已改文件：路径 + 每个文件改了什么（一行一个）
4. 踩过的错：错误信息 + 最终怎么解决的
5. 关键代码片段：正在改的函数签名/接口（原文保留）
6. 用户插话：所有用户中途给的指示（逐条保留）
7. 待办事项：计划里还没做完的步骤
8. 当前进展：压缩那一刻正在干什么、下一步是什么"""


class AgentCompressMixin:
    """历史压缩与摘要落盘的 Mixin，供 AgentBase 继承。"""

    async def _structured_compress(self, messages: list[dict],
                                   session_id: str = "") -> list[dict]:
        """H3: 用 LLM 生成八段式结构化摘要替代占位符。失败回退 _compress_history。"""
        if len(messages) <= 10:
            return messages
        sys_msgs = [m for m in messages if m["role"] == "system"]
        rest = [m for m in messages if m["role"] != "system"]
        first_user = next((m for m in rest if m["role"] == "user"), None)
        tail = rest[-6:] if len(rest) > 6 else rest
        while tail and tail[0].get("role") == "tool":
            tail = tail[1:]
        dropped = [m for m in rest if m is not first_user and m not in tail]
        if not dropped:
            return self._compress_history(messages)
        history_lines = []
        for m in dropped[-30:]:
            role = m.get("role", "?")
            c = m.get("content") or ""
            if isinstance(c, list):
                c = str(c)[:300]
            elif len(c) > 400:
                c = c[:400] + "…"
            tcs = m.get("tool_calls") or []
            if tcs:
                names = [tc.get("function", {}).get("name", "?") for tc in tcs]
                c = f"[调用工具: {', '.join(names)}]"
            history_lines.append(f"[{role}] {c}")
        prompt = _STRUCTURED_PROMPT.format(history="\n".join(history_lines))
        try:
            resp = await self._call_api(
                [{"role": "user", "content": prompt}],
                tools=None, stream=False,
                override_model="DeepSeek-V4-Flash",
            )
            summary_text = (resp.get("content") or "").strip()
            if not summary_text or len(summary_text) < 50:
                raise ValueError("摘要过短或为空")
        except Exception:
            return self._compress_history(messages)
        result = sys_msgs[:]
        if first_user:
            result.append(first_user)
        result.append({"role": "assistant",
                        "content": f"[结构化摘要（中间 {len(dropped)} 条消息已压缩）]\n\n{summary_text}"})
        return result + self._evict_large_results(tail)

    def _compress_history(self, messages: list[dict]) -> list[dict]:
        if len(messages) <= 10:
            return messages
        sys_msgs = [m for m in messages if m["role"] == "system"]
        rest = [m for m in messages if m["role"] != "system"]
        first_user = next((m for m in rest if m["role"] == "user"), None)
        tail = rest[-6:] if len(rest) > 6 else rest
        # 防止 tail 从工具调用序列中间切断：若开头是孤儿 tool 消息（其对应的
        # assistant.tool_calls 已被压缩掉），供应商会报 400
        # "tool must be a response to a preceding message with tool_calls"。
        # 剥掉开头所有悬空的 tool 消息。
        while tail and tail[0].get("role") == "tool":
            tail = tail[1:]
        result = sys_msgs[:]
        if first_user and first_user not in tail:
            result.append(first_user)
            placeholder = "[中间对话已压缩]"
            if self.coding_compress:
                dropped = [m for m in rest if m is not first_user and m not in tail]
                digest = self._coding_digest(dropped)
                if digest:
                    placeholder = placeholder + "\n\n" + digest
            result.append({"role": "assistant", "content": placeholder})
        return result + self._evict_large_results(tail)

    @staticmethod
    def _evict_large_results(msgs: list[dict], threshold: int = 4096) -> list[dict]:
        """H7: 压缩事件时驱逐超大工具结果，替换为指纹占位。
        只处理 tool 角色消息，其余原样保留。"""
        out = []
        for m in msgs:
            if m.get("role") == "tool":
                c = m.get("content") or ""
                if len(c) > threshold:
                    fp = hashlib.sha256(c.encode()).hexdigest()[:12]
                    m = {**m, "content": f"[已驱逐 {len(c)} 字符，SHA:{fp}，需要时重新读取]"}
            out.append(m)
        return out

    def _coding_digest(self, dropped: list[dict]) -> str:
        """从被压缩掉的中间消息里提炼"已改文件 + 关键命令/退出码"摘要，
        让编程 agent 在长会话里不会忘记前面已经动过什么、测试通没通过。"""
        files: list[str] = []           # 保序去重
        seen_files: set[str] = set()
        commands: list[str] = []        # (command, exit_code?) 文本，保留最近若干条
        pending_cmd: str | None = None  # 上一条 assistant 发起的 shell_run，等其结果配退出码

        for m in dropped:
            role = m.get("role")
            if role == "assistant":
                for tc in (m.get("tool_calls") or []):
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except Exception:
                        args = {}
                    if name in ("file_write", "file_edit") and args.get("path"):
                        p = args["path"]
                        if p not in seen_files:
                            seen_files.add(p)
                            files.append(p)
                    elif name == "shell_run" and args.get("command"):
                        pending_cmd = str(args["command"])[:80]
            elif role == "tool":
                if pending_cmd is not None:
                    code = ""
                    try:
                        d = json.loads(m.get("content") or "{}")
                        if isinstance(d, dict) and "exit_code" in d:
                            code = f" → exit={d['exit_code']}"
                    except Exception:
                        pass
                    commands.append(pending_cmd + code)
                    pending_cmd = None

        parts: list[str] = []
        if files:
            shown = files[-20:]
            parts.append("## 期间已改文件\n" + "\n".join(f"- {p}" for p in shown))
        if commands:
            shown = commands[-8:]
            parts.append("## 期间关键命令\n" + "\n".join(f"- {c}" for c in shown))
        return "\n\n".join(parts)

    async def _async_compress(self, session_id, messages, summary, files_changed, turns):
        async with self._compress_semaphore:
            for attempt in range(1, 4):
                try:
                    key_msgs = []
                    for m in messages[-15:]:
                        c = m.get("content", "") or ""
                        if len(c) > 600:
                            c = c[:600] + "…"
                        key_msgs.append(f"[{m['role']}] {c}")
                    prompt = (
                        f"请生成9段式任务摘要（每段2-3句，总计800字内）。\n"
                        f"任务: {summary[:500]}\n轮数: {turns}\n文件: {', '.join(files_changed) or '无'}\n"
                        f"历史:\n{'  '.join(key_msgs)}\n\n"
                        "输出格式: 1.会话目标 2.已完成 3.未完成 4.关键决策 5.代码变更 6.发现问题 7.待验证 8.用户偏好 9.上下文"
                    )
                    resp = await self._call_api([{"role": "user", "content": prompt}],
                                                tools=None, stream=False)
                    if "error" in resp or not resp.get("content", "").strip():
                        raise RuntimeError(resp.get("error", "空摘要"))
                    out_path = self._notes_dir / f"{datetime.now().strftime('%Y-%m-%d')}_{session_id}.md"
                    header = (f"# {self.name} · {session_id}\n"
                              f"- 时间: {datetime.now().isoformat()}\n"
                              f"- 轮数: {turns}\n"
                              f"- 文件: {', '.join(files_changed) or '无'}\n\n")
                    out_path.write_text(header + resp["content"], encoding="utf-8")
                    self._log(session_id, "compress_ok", {"path": str(out_path)})
                    return
                except Exception:
                    await asyncio.sleep(2 ** attempt)
            self._log(session_id, "compress_failed", {})

    def _scan_previous_summary(self) -> str:
        try:
            files = sorted(self._notes_dir.glob(f"*_{self.name}-*.md"),
                           key=lambda f: f.stat().st_mtime, reverse=True)
            if not files:
                return ""
            content = files[0].read_text(encoding="utf-8")
            segs = re.findall(r"\d+\.[会已未关代发待用上].*?(?=\n\d+\.|$)", content, re.DOTALL)
            head4 = "\n".join(segs[:4])[:500]
            return f"\n\n## 上次任务回顾\n{head4}" if head4 else ""
        except Exception:
            return ""
