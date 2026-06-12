#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentBase — Anima 员工基类
可移植版本：所有路径通过 config.py 配置，无硬编码
"""
import json, os, re, sys, time, hashlib, asyncio, inspect
from pathlib import Path
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import aiohttp

sys.path.insert(0, str(Path(__file__).parent))

# ── Mixin 分层（历史压缩 / 日志）─────────────────────────────────────────────
from agent_compress import AgentCompressMixin
from agent_logging  import AgentLoggingMixin


# ── 权限请求异常（Agent 发现缺少 API 时抛出）─────────────
class PermissionRequest(Exception):
    """
    Agent 在执行任务时发现缺少某个 API Key 或权限时抛出。
    前端捕获后显示权限请求卡片，引导用户配置。
    """
    def __init__(self, api_name: str, reason: str,
                 signup_url: str = "", alternatives: list = None,
                 related: list = None):
        self.api_name    = api_name       # 例：「搜索 API」
        self.reason      = reason         # 例：「执行网络搜索需要配置搜索服务」
        self.signup_url  = signup_url     # 官网注册链接
        self.alternatives = alternatives or []   # 备选 API
        self.related      = related or []        # 同类配置建议
        super().__init__(f"需要权限: {api_name} — {reason}")
from config import (
    LOG_DIR, WORKSPACE_DIR,
    DEEPSEEK_KEY, OPENAI_KEY, ANTHROPIC_KEY,
    QWEN_KEY, KIMI_KEY, GLM_KEY, MIMO_KEY, GEMINI_KEY, OPENROUTER_KEY,
    GLM_URL, MIMO_URL,
)

# ── 模型注册表：前端显示名 → API 参数 ──────────────────────────────────────
# 格式: display_name → (api_key_fn, base_url, api_model_id)
# 中转站地址：可在 config.yaml 中通过 api.relay_url 自定义
def _get_relay():
    """中转站地址。仅从配置读取，未配置则返回空字符串。"""
    try:
        from config import _get as _cfg_get
        url = _cfg_get("api.relay_url", "")
        if url:
            return url.rstrip("/")
    except Exception:
        pass
    return ""

_RELAY = _get_relay()
_DS    = "https://api.deepseek.com"
_QWEN  = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_KIMI  = "https://api.moonshot.cn/v1"
_GLM   = GLM_URL
_MIMO  = MIMO_URL

MODEL_REGISTRY: dict[str, tuple] = {
    "DeepSeek-V4-Pro":   (lambda: DEEPSEEK_KEY, _DS, "deepseek-v4-pro"),
    "DeepSeek-V4-Flash": (lambda: DEEPSEEK_KEY, _DS, "deepseek-v4-flash"),
    "DeepSeek-R1":       (lambda: DEEPSEEK_KEY, _DS, "deepseek-reasoner"),
    "DeepSeek-V3":       (lambda: DEEPSEEK_KEY, _DS, "deepseek-chat"),
    "Qwen3.7-Max":       (lambda: QWEN_KEY, _QWEN, "qwen3.7-max"),
    "Qwen3.6-Plus":      (lambda: QWEN_KEY, _QWEN, "qwen3.6-plus"),
    "Qwen3.6-Flash":     (lambda: QWEN_KEY, _QWEN, "qwen3.6-flash"),
    "Qwen3.5-Plus":      (lambda: QWEN_KEY, _QWEN, "qwen3.5-plus"),
    "Qwen3-Max":         (lambda: QWEN_KEY, _QWEN, "qwen3-max"),
    "QwQ-Plus":          (lambda: QWEN_KEY, _QWEN, "qwq-plus"),
    "Qwen-Long":         (lambda: QWEN_KEY, _QWEN, "qwen-long"),
    "Kimi-K2.6":         (lambda: KIMI_KEY, _KIMI, "kimi-k2.6"),
    "Kimi-K2.5":         (lambda: KIMI_KEY, _KIMI, "kimi-k2.5"),
    "Kimi-Auto":         (lambda: KIMI_KEY, _KIMI, "moonshot-v1-auto"),
    "Kimi-128K":         (lambda: KIMI_KEY, _KIMI, "moonshot-v1-128k"),
    "Kimi-32K":          (lambda: KIMI_KEY, _KIMI, "moonshot-v1-32k"),
    "Kimi-8K":           (lambda: KIMI_KEY, _KIMI, "moonshot-v1-8k"),
    "GLM-4.6":           (lambda: GLM_KEY, _GLM, "glm-4.6"),
    "GLM-4-Plus":        (lambda: GLM_KEY, _GLM, "glm-4-plus"),
    "GLM-4-Air":         (lambda: GLM_KEY, _GLM, "glm-4-air"),
    "GLM-4-Flash":       (lambda: GLM_KEY, _GLM, "glm-4-flash"),
    "MiMo-7B":           (lambda: MIMO_KEY, _MIMO, "mimo-7b-rl"),
    "MiMo-VL":           (lambda: MIMO_KEY, _MIMO, "mimo-vl-7b-rl"),
    "GPT-5.5":            (lambda: OPENROUTER_KEY, _RELAY, "gpt-5.5"),
    "GPT-5.5-Compact":    (lambda: OPENROUTER_KEY, _RELAY, "gpt-5.5-openai-compact"),
    "GPT-5.4":            (lambda: OPENROUTER_KEY, _RELAY, "gpt-5.4"),
    "Claude-Opus-4.6":       (lambda: OPENROUTER_KEY, _RELAY, "claude-opus-4.6"),
    "Claude-Opus-4.6-Think": (lambda: OPENROUTER_KEY, _RELAY, "claude-opus-4-6-thinking"),
    "Claude-Sonnet-4.6":     (lambda: OPENROUTER_KEY, _RELAY, "claude-sonnet-4.6"),
    "Claude-Haiku-4.5":      (lambda: OPENROUTER_KEY, _RELAY, "claude-haiku-4-5-20251001"),
}

_FALLBACK_CHAIN = [
    (lambda: DEEPSEEK_KEY,   _DS,   "deepseek-chat"),
    (lambda: KIMI_KEY,       _KIMI, "kimi-k2.5"),
    (lambda: QWEN_KEY,       _QWEN, "qwen3.6-plus"),
    (lambda: GLM_KEY,        _GLM,  "glm-4-plus"),
    (lambda: MIMO_KEY,       _MIMO, "mimo-7b-rl"),
    (lambda: OPENROUTER_KEY, _RELAY, "claude-sonnet-4.6"),
]

def first_available_model() -> tuple[str, str, str]:
    """返回首个已配置 provider 的 (api_key, base_url, model_id)；都没配则返回空。"""
    for key_fn, base_url, model_id in _FALLBACK_CHAIN:
        k = key_fn()
        if k and base_url:
            return k, base_url, model_id
    return "", "", ""


class AgentBase(AgentCompressMixin, AgentLoggingMixin):
    """所有数字员工的基类。提供 ReAct 循环、三层压缩、日志。"""

    def __init__(self, name: str, api_key: str, model: str, base_url: str,
                 system_prompt: str, tool_defs: list[dict], tool_dispatch: dict,
                 log_dir: Path | None = None, work_dir: Path | None = None):
        self.name = name
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.system_prompt = system_prompt
        self.tool_defs = tool_defs
        self.tool_dispatch = tool_dispatch

        # 使用 config 默认值，允许子类覆盖
        self.log_dir  = Path(log_dir)  if log_dir  else LOG_DIR
        self.work_dir = Path(work_dir) if work_dir else WORKSPACE_DIR / name
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # 压缩 & 去重（去重集合改为 per-run 局部，避免并发会话相互污染）
        self._compress_semaphore = asyncio.Semaphore(1)
        self._compression_pending = False

        # 飞书推送（可选）
        self._feishu_app_id     = os.getenv("FEISHU_APP_ID", "")
        self._feishu_app_secret = os.getenv("FEISHU_APP_SECRET", "")
        self._feishu_chat_id    = os.getenv("FEISHU_CHAT_ID", "")

        # 笔记存储目录（Obsidian 或本地）
        obsidian_env = os.getenv("OBSIDIAN_VAULT", "")
        self._notes_dir = Path(obsidian_env) if obsidian_env and Path(obsidian_env).exists() \
                          else self.work_dir / "notes"
        self._notes_dir.mkdir(parents=True, exist_ok=True)

        # 运行时
        self.max_turns         = 60
        self.compress_every    = 5
        self.context_cap_chars = 8000
        # 累计输入预算（字符）：每轮 API 调用都会重发整个 messages，
        # 累计成本 ≈ Σ(每轮 messages 大小)。超出则优雅收尾，
        # 防止大文件循环 / 失控 ReAct 在 180s 超时前烧光额度。约 ~200k tokens。
        self.max_total_chars   = 800_000
        # 工具结果回传给模型时的截断上限（per-agent 可覆盖）。
        # 默认值对聊天型人格友好（控制上下文膨胀）；编程/阅读型子类需调大，
        # 否则看不全代码 = 半瞎改 = 花架子。
        #   tool_result_cap : 普通工具结果的最终截断长度
        #   file_read_cap   : file_read 内容超此值则只回指纹（设大才能真读代码）
        self.tool_result_cap = 500
        self.file_read_cap   = 2048
        # 编程向历史压缩（M9 Part 3）：默认 False = 旧行为（中间段落直接丢成占位符）。
        # 编程型子类（executor）置 True：压缩时从被丢弃的中间消息里提炼一份
        # "已改文件 + 关键命令/退出码" 摘要塞进占位符，长会话里不会忘记自己改过什么。
        self.coding_compress = False
        # 去 AI 味（聊天人格置 True）：最终回复经 _humanize 清洗掉 Markdown 装饰符号
        #（**加粗** / ## 标题 / 项目符号 / 破折号 ——），保护代码块不动。
        # 子 agent（executor/writer/...）保持 False：它们的产出要进代码/报告，符号有意义。
        self.humanize_output = False
        # 采样温度：None = 用供应商默认；聊天人格略调高，回复更自然不刻板。
        self.temperature = None

    # ── 子类必须实现 ──
    def get_identity_files(self) -> dict[str, Path]:
        return {}

    # ── 模型路由 ──
    def _resolve_model(self, display_name: str | None) -> tuple[str, str, str]:
        """将前端显示名解析为 (api_key, base_url, model_id)。
        若未找到或 API Key 为空则回退到本 agent 默认配置。"""
        if display_name and display_name in MODEL_REGISTRY:
            key_fn, base_url, model_id = MODEL_REGISTRY[display_name]
            key = key_fn()
            if key:  # API Key 已配置才切换
                if not base_url:
                    # 中转模型（GPT/Claude）但未配置 api.relay_url
                    raise PermissionRequest(
                        api_name="中转服务地址",
                        reason=f"使用 {display_name} 需要先在设置中配置中转站地址（api.relay_url）。"
                               f"DeepSeek / Qwen / Kimi 为直连，无需中转。",
                        signup_url="",
                        related=["relay_url"],
                    )
                return key, base_url, model_id
            # 选了某模型但其 provider 未配 → 落到首个已配 provider（单 key 即可用全功能）
            fk, fu, fm = first_available_model()
            if fk:
                return fk, fu, fm
        # agent 默认；若默认 provider 也没配，落到首个已配 provider
        if self.api_key and self.base_url:
            return self.api_key, self.base_url, self.model
        fk, fu, fm = first_available_model()
        return (fk, fu, fm) if fk else (self.api_key, self.base_url, self.model)

    # ── API ──
    async def _call_api(self, messages: list[dict], tools: list[dict] | None = None,
                        stream: bool = True, override_model: str | None = None,
                        on_delta=None) -> dict:
        api_key, base_url, model_id = self._resolve_model(override_model)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {"model": model_id, "messages": messages, "stream": stream}
        if tools:
            body["tools"] = tools
        if self.temperature is not None:
            body["temperature"] = self.temperature

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/chat/completions",
                headers=headers, json=body,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status != 200:
                    return {"error": f"API {resp.status}: {(await resp.text())[:500]}"}
                return await self._handle_stream(resp, on_delta=on_delta) if stream else self._extract_response(await resp.json())

    async def _handle_stream(self, resp, on_delta=None) -> dict:
        content = reasoning = ""
        tool_calls: list[dict] = []
        async for line in resp.content:
            line_text = line.decode("utf-8", errors="replace").strip()
            if not line_text.startswith("data: "):
                continue
            data_str = line_text[6:]
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            # 某些供应商（DeepSeek/Qwen 等）会发 choices 为空的统计 chunk（仅含 usage），
            # 此时 [0] 会越界——空 choices 直接跳过。
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            if delta.get("reasoning_content"):
                reasoning += delta["reasoning_content"]
            if delta.get("content"):
                content += delta["content"]
                if on_delta:
                    await on_delta(delta["content"])
            if "tool_calls" in delta:
                for tc in delta["tool_calls"]:
                    idx = tc.get("index", 0)
                    while len(tool_calls) <= idx:
                        tool_calls.append({"id": "", "type": "function",
                                            "function": {"name": "", "arguments": ""}})
                    if "id" in tc:
                        tool_calls[idx]["id"] = tc["id"]
                    if "function" in tc:
                        if tc["function"].get("name"):
                            tool_calls[idx]["function"]["name"] = tc["function"]["name"]
                        tool_calls[idx]["function"]["arguments"] += tc["function"].get("arguments", "")
        return {"content": content, "reasoning_content": reasoning,
                "tool_calls": tool_calls or None}

    def _extract_response(self, data: dict) -> dict:
        msg = data.get("choices", [{}])[0].get("message", {})
        return {"content": msg.get("content", ""),
                "reasoning_content": msg.get("reasoning_content", ""),
                "tool_calls": msg.get("tool_calls")}

    # ── ReAct 主循环 ──
    async def run(self, task: str, session_id: str | None = None,
                  model: str | None = None, ws=None,
                  project: str | None = None) -> dict:
        """运行 ReAct 循环。
        ws:      可选的 aiohttp WebSocketResponse，若提供则实时推送工具调用事件。
        project: 可选的项目名称，注入项目上下文。
        """
        if session_id is None:
            session_id = f"{self.name}-{int(time.time())}"

        # ── 注入 Vault 记忆 + 活跃项目上下文（让 Agent 认识用户）──
        try:
            from memory_injector import (
                get_memory_injection, get_project_context,
                get_active_project_context, get_memory_self_description,
                reset_session_writes,
            )
            import pref_learning
            reset_session_writes(self.name)   # M3：每次 run() 重置单会话写入计数
            memory_ctx = get_memory_injection(self.name, query=task) + get_memory_self_description(self.name)
            memory_ctx += pref_learning.get_work_room_injection(self.name)  # M10：E 程序层偏好规则（仅工作房间）
            # 优先：明确传入的 project 参数；其次：当前活跃项目；最后：无
            if project:
                project_ctx = get_project_context(project)
            else:
                project_ctx = get_active_project_context()
        except Exception:
            memory_ctx = project_ctx = ""

        prev = self._scan_previous_summary()
        system_content = self.system_prompt + prev + memory_ctx + project_ctx
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user",   "content": f"## 任务\n\n{self._normalize(task)}"},
        ]
        files_changed: list[str] = []
        seen_hashes: set[str] = set()   # 本次运行专属的工具结果去重集合
        total_chars = 0                 # 累计已发送给 API 的输入字符（预算护栏）
        # 记录实际使用的模型（用于日志）
        _used_key, _used_url, _used_model = self._resolve_model(model)
        self._log(session_id, "session_start", {"task": task[:200], "model": _used_model})

        async def _ws_send(payload: dict):
            """安全发送 WS 消息，忽略任何发送错误。"""
            if ws is None:
                return
            try:
                await ws.send_json(payload)
            except Exception:
                pass

        on_delta = None
        if ws is not None:
            async def _on_delta(chunk: str):
                await _ws_send({"type": "assistant_delta", "data": {"content": chunk}})
            on_delta = _on_delta

        # 内核3：工具上下文（确认/钩子用）。默认策略全 off + 默认无钩子 → 零行为变化。
        tool_ctx = {"ws": ws, "session_id": session_id, "agent": self.name}

        for turn in range(1, self.max_turns + 1):
            if turn > 1 and turn % self.compress_every == 0:
                old = len(messages)
                messages = self._compress_history(messages)
                if len(messages) < old:
                    self._log(session_id, "compress", {"turn": turn, "before": old, "after": len(messages)})

            # ── token 预算护栏：累计输入超限则优雅收尾 ──
            total_chars += sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
            if total_chars > self.max_total_chars:
                self._log(session_id, "budget_exceeded",
                          {"turn": turn, "total_chars": total_chars})
                summary = (f"已达输入预算上限（约 {self.max_total_chars // 1000}k 字符），"
                           f"在第 {turn} 轮停止以避免额度失控。")
                return {"status": "budget_exceeded", "summary": summary,
                        "files_changed": files_changed, "turn_count": turn}

            resp = await self._call_api(messages, tools=self.tool_defs, override_model=model, on_delta=on_delta)
            if "error" in resp:
                self._log(session_id, "api_error", {"turn": turn, "error": resp["error"]})
                return {"status": "error", "error": resp["error"], "turn_count": turn}

            assistant_msg: dict = {
                "role": "assistant",
                "reasoning_content": resp.get("reasoning_content", ""),
            }
            if resp.get("tool_calls"):
                assistant_msg["tool_calls"] = resp["tool_calls"]
                assistant_msg["content"] = resp.get("content") or None
            else:
                assistant_msg["content"] = resp.get("content", "")
            messages.append(assistant_msg)

            # 无工具调用 = 完成
            if not resp.get("tool_calls"):
                summary = resp.get("content", "")
                if self.humanize_output:
                    summary = self._humanize(summary)
                self._log(session_id, "session_complete", {"turns": turn, "files_changed": files_changed})
                asyncio.create_task(self._async_compress(session_id, messages, summary, files_changed, turn))
                asyncio.create_task(self._notify_feishu(session_id, "completed", turn, files_changed))
                return {"status": "completed", "summary": summary,
                        "files_changed": files_changed, "turn_count": turn}

            # ── 执行工具（含实时推流）──
            for tc in resp["tool_calls"]:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                    result = {"error": f"参数解析失败: {tc['function']['arguments'][:200]}"}
                else:
                    # 推送 tool_start 事件（截断参数值避免过长）
                    safe_args = {k: (str(v)[:120] + "…" if len(str(v)) > 120 else str(v))
                                 for k, v in args.items()}
                    await _ws_send({
                        "type": "tool_start",
                        "data": {"tool": name, "args": safe_args, "turn": turn},
                    })
                    result = await self._execute_tool(name, args, ctx=tool_ctx)

                if name in ("file_write", "file_edit") and "error" not in result:
                    if p := result.get("path"):
                        files_changed.append(p)

                # 推送 tool_done 事件
                await _ws_send({
                    "type": "tool_done",
                    "data": {
                        "tool": name,
                        "ok":   "error" not in result,
                        "turn": turn,
                        "hint": str(result.get("error", ""))[:80] if "error" in result else "",
                    },
                })

                self._log(session_id, "tool_call", {
                    "turn": turn, "tool": name, "success": "error" not in result,
                })
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{turn}"),
                }
                if isinstance(result, dict) and "_vision_block" in result:
                    tool_msg["content"] = result["_vision_block"]
                else:
                    tool_msg["content"] = self._trim_result(name, result, seen_hashes)
                messages.append(tool_msg)

            if sum(len(json.dumps(m, ensure_ascii=False)) for m in messages) > self.context_cap_chars * 3:
                messages = self._compress_history(messages)

        return {"status": "max_turns_reached",
                "summary": f"达到最大轮数 {self.max_turns}", "turn_count": self.max_turns}

    async def _execute_tool(self, name: str, args: dict, ctx: dict | None = None) -> dict:
        """工具调用的全局唯一咽喉。

        内核1（异步化）：同步工具返回 dict（iscoroutine=False，行为与旧版完全一致）；
            异步工具（MCP / 任何 async 回调）返回协程，在此 await。
        内核3（确认 / Hooks）：仅当传入 ctx 时启用——pre_tool 钩子可否决、危险操作
            走 confirm 往返、post_tool 钩子收尾。ctx=None（含所有单测直调）时整条
            确认/钩子链跳过，路径与内核1 时期字节级一致，故向后兼容不破。
            默认策略全 off、默认无钩子，所以即便传 ctx，默认配置下也零行为变化。
        """
        if name not in self.tool_dispatch:
            return {"error": f"未知工具: {name}"}
        if ctx is not None:
            blocked = await self._guard_tool(name, args, ctx)
            if blocked is not None:
                return blocked
        try:
            result = self.tool_dispatch[name](**args)
            if inspect.iscoroutine(result):
                result = await result
        except PermissionRequest:
            raise   # 权限请求必须向上传播，由 websocket_server 捕获并推送卡片
        except TypeError as e:
            result = {"error": f"工具参数错误: {e}"}
        except Exception as e:
            result = {"error": f"工具执行异常: {e}"}
        if ctx is not None:
            await self._post_tool(name, args, result, ctx)
        return result

    async def _guard_tool(self, name: str, args: dict, ctx: dict) -> dict | None:
        """咽喉前置：pre_tool 钩子（可否决）+ 危险操作确认。
        返回 None=放行；返回 dict=拦下（作为工具结果回给模型）。"""
        try:
            from hooks import run_pre_tool
            veto = await run_pre_tool(name, args, ctx)
            if veto is not None:
                return veto
        except Exception:
            pass
        try:
            from confirm import get_broker, classify
            kind = classify(name, args)
            if kind and not await get_broker().guard(kind, name, args, ctx):
                return {"error": f"操作被拒绝（{kind}）: {name}", "cancelled": True}
        except PermissionRequest:
            raise
        except Exception:
            pass
        return None

    async def _post_tool(self, name: str, args: dict, result: dict, ctx: dict) -> None:
        """咽喉后置：post_tool 钩子（如自动格式化）。异常不影响工具结果。"""
        try:
            from hooks import run_post_tool
            await run_post_tool(name, args, result, ctx)
        except Exception:
            pass

    # ── 工具 ──
    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", text.strip().replace("\r\n", "\n"))

    @staticmethod
    def _humanize(text: str) -> str:
        """去 AI 味：剥掉 Markdown 装饰符号，让回复读起来像真人发的消息。
        只动格式符号，不改一个字的内容；围栏代码块与行内代码原样保护。"""
        if not text or "\x00" in text:
            return text
        # 1) 先把代码块/行内代码抠出来占位，避免误伤代码里的 * # - 等
        stash: list[str] = []
        def _keep(m):
            stash.append(m.group(0))
            return f"\x00{len(stash) - 1}\x00"
        text = re.sub(r"```.*?```", _keep, text, flags=re.DOTALL)
        text = re.sub(r"`[^`\n]+`", _keep, text)
        # 2) 去标题井号，保留标题文字
        text = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]+", "", text)
        # 3) 去 **加粗** __加粗__ ~~删除线~~，保留内文
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"__(.+?)__", r"\1", text)
        text = re.sub(r"~~(.+?)~~", r"\1", text)
        # 4) 去行首项目符号（- * +），保留这一行的文字
        text = re.sub(r"(?m)^[ \t]*[-*+][ \t]+", "", text)
        # 4b) 去行首编号清单标记「1. 」「2、」，保留文字。只匹配 1-2 位数字 + 标点
        #     + 空格，避开版本号 3.14（无空格）、年份 2024.（4 位）等。
        text = re.sub(r"(?m)^[ \t]*\d{1,2}[.、][ \t]+", "", text)
        # 5) 破折号：双破折号 —— → 逗号；单破折号仅在非数字间替换（保留 3—5 这类区间）
        text = text.replace("——", "，")
        text = re.sub(r"(?<!\d)—(?!\d)", "，", text)
        # 6) 收尾：连续逗号、逗号紧贴句末标点、过多空行
        text = re.sub(r"，{2,}", "，", text)
        text = re.sub(r"，([。！？，、])", r"\1", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 7) 还原代码
        text = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)
        return text.strip()

    def _trim_result(self, tool_name: str, result: dict, seen: set[str]) -> str:
        text = json.dumps(result, ensure_ascii=False)
        h = hashlib.sha256(text.encode()).hexdigest()
        if h in seen:
            return json.dumps({"_dedup": True, "sha256": h[:12]}, ensure_ascii=False)
        seen.add(h)
        # URL 缩短
        text = re.sub(r"https?://[^\s<>\"{}|\\^`\[\]]{20,}",
                      lambda m: f"{m.group(0)[:40]}…", text)
        if tool_name == "file_read" and len(text) > self.file_read_cap:
            try:
                d = json.loads(text)
                c = d.get("content", "")
                if len(c) > self.file_read_cap:
                    return json.dumps({"fingerprint": f"[{len(c)}字符 | SHA:{h[:8]}]",
                                       "note": "文件过大已压缩"}, ensure_ascii=False)
            except Exception:
                pass
        cap = self.tool_result_cap
        return text[:cap] + f"…[截断,原长{len(text)}字符]" if len(text) > cap else text

    # ── _compress_history / _coding_digest / _async_compress / _scan_previous_summary
    # 已移入 AgentCompressMixin（agent_compress.py）
    # ──────────────────────────────────────────────────────────────────────────────

    # ── _log / _notify_feishu 已移入 AgentLoggingMixin（agent_logging.py）──────
