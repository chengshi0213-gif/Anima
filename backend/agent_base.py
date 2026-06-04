#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentBase — Anima 员工基类
可移植版本：所有路径通过 config.py 配置，无硬编码
"""
import json, os, re, sys, time, hashlib, asyncio
from pathlib import Path
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import aiohttp

sys.path.insert(0, str(Path(__file__).parent))


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
# 格式: display_name → (api_key_var, base_url, api_model_id)
# OpenRouter 作为 Claude/Gemini 的兜底（兼容 OpenAI 协议）
# 中转站地址：可在 config.yaml 中通过 api.relay_url 自定义
def _get_relay():
    """中转站地址。仅从配置读取，未配置则返回空字符串——
    不再兜底到任何硬编码服务器（避免裸 IP 单点 + 流量外泄面）。"""
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
_GLM   = GLM_URL    # 智谱 GLM（open.bigmodel.cn，OpenAI 兼容）
_MIMO  = MIMO_URL   # 小米 MiMo（OpenAI 兼容，base_url 可在 config.yaml 覆盖）

MODEL_REGISTRY: dict[str, tuple] = {
    # ── DeepSeek 直连 ─────────────────────────────────────────────────────
    "DeepSeek-V4-Pro":   (lambda: DEEPSEEK_KEY, _DS, "deepseek-v4-pro"),    # 最强
    "DeepSeek-V4-Flash": (lambda: DEEPSEEK_KEY, _DS, "deepseek-v4-flash"),  # 最快
    "DeepSeek-R1":       (lambda: DEEPSEEK_KEY, _DS, "deepseek-reasoner"),  # 推理
    "DeepSeek-V3":       (lambda: DEEPSEEK_KEY, _DS, "deepseek-chat"),      # 经济/兼容

    # ── 阿里 Qwen 直连（DashScope）────────────────────────────────────────
    "Qwen3.7-Max":       (lambda: QWEN_KEY, _QWEN, "qwen3.7-max"),          # 最新旗舰
    "Qwen3.6-Plus":      (lambda: QWEN_KEY, _QWEN, "qwen3.6-plus"),         # 高性价比
    "Qwen3.6-Flash":     (lambda: QWEN_KEY, _QWEN, "qwen3.6-flash"),        # 最快
    "Qwen3.5-Plus":      (lambda: QWEN_KEY, _QWEN, "qwen3.5-plus"),         # 稳定
    "Qwen3-Max":         (lambda: QWEN_KEY, _QWEN, "qwen3-max"),            # 上代旗舰
    "QwQ-Plus":          (lambda: QWEN_KEY, _QWEN, "qwq-plus"),             # 深度推理
    "Qwen-Long":         (lambda: QWEN_KEY, _QWEN, "qwen-long"),            # 超长文

    # ── Moonshot Kimi 直连 ────────────────────────────────────────────────
    "Kimi-K2.6":         (lambda: KIMI_KEY, _KIMI, "kimi-k2.6"),            # 最新旗舰
    "Kimi-K2.5":         (lambda: KIMI_KEY, _KIMI, "kimi-k2.5"),            # 上一代旗舰
    "Kimi-Auto":         (lambda: KIMI_KEY, _KIMI, "moonshot-v1-auto"),     # 自动选档
    "Kimi-128K":         (lambda: KIMI_KEY, _KIMI, "moonshot-v1-128k"),     # 超长上下文
    "Kimi-32K":          (lambda: KIMI_KEY, _KIMI, "moonshot-v1-32k"),      # 均衡
    "Kimi-8K":           (lambda: KIMI_KEY, _KIMI, "moonshot-v1-8k"),       # 经济

    # ── 智谱 GLM 直连（open.bigmodel.cn）─────────────────────────────────
    "GLM-4.6":           (lambda: GLM_KEY, _GLM, "glm-4.6"),                # 最新旗舰
    "GLM-4-Plus":        (lambda: GLM_KEY, _GLM, "glm-4-plus"),             # 高性能
    "GLM-4-Air":         (lambda: GLM_KEY, _GLM, "glm-4-air"),              # 高性价比
    "GLM-4-Flash":       (lambda: GLM_KEY, _GLM, "glm-4-flash"),            # 免费/最快

    # ── 小米 MiMo 直连（OpenAI 兼容）──────────────────────────────────────
    "MiMo-7B":           (lambda: MIMO_KEY, _MIMO, "mimo-7b-rl"),           # 推理强化
    "MiMo-VL":           (lambda: MIMO_KEY, _MIMO, "mimo-vl-7b-rl"),        # 多模态

    # ── GPT（via 中转，需配置 OpenRouter Key）────────────────────────────
    "GPT-5.5":            (lambda: OPENROUTER_KEY, _RELAY, "gpt-5.5"),                  # 旗舰
    "GPT-5.5-Compact":    (lambda: OPENROUTER_KEY, _RELAY, "gpt-5.5-openai-compact"),   # 快速
    "GPT-5.4":            (lambda: OPENROUTER_KEY, _RELAY, "gpt-5.4"),                  # 均衡

    # ── Claude（via 中转，需配置 OpenRouter Key）─────────────────────────
    "Claude-Opus-4.6":       (lambda: OPENROUTER_KEY, _RELAY, "claude-opus-4.6"),          # 最强
    "Claude-Opus-4.6-Think": (lambda: OPENROUTER_KEY, _RELAY, "claude-opus-4-6-thinking"), # 深度推理
    "Claude-Sonnet-4.6":     (lambda: OPENROUTER_KEY, _RELAY, "claude-sonnet-4.6"),        # 均衡
    "Claude-Haiku-4.5":      (lambda: OPENROUTER_KEY, _RELAY, "claude-haiku-4-5-20251001"),# 最快
}

# 单 key 即可用全功能：任何模型/agent 拿不到 key 时，落到「首个已配 provider」的稳健默认模型。
# 优先级：DeepSeek > Kimi > Qwen > 中转(GPT/Claude)。
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


class AgentBase:
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
                        stream: bool = True, override_model: str | None = None) -> dict:
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
                return await self._handle_stream(resp) if stream else self._extract_response(await resp.json())

    async def _handle_stream(self, resp) -> dict:
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
            )
            memory_ctx = get_memory_injection(self.name) + get_memory_self_description(self.name)
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

            resp = await self._call_api(messages, tools=self.tool_defs, override_model=model)
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
                    result = self._execute_tool(name, args)

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
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{turn}"),
                    "content": self._trim_result(name, result, seen_hashes),
                })

            if sum(len(json.dumps(m, ensure_ascii=False)) for m in messages) > self.context_cap_chars * 3:
                messages = self._compress_history(messages)

        return {"status": "max_turns_reached",
                "summary": f"达到最大轮数 {self.max_turns}", "turn_count": self.max_turns}

    def _execute_tool(self, name: str, args: dict) -> dict:
        if name not in self.tool_dispatch:
            return {"error": f"未知工具: {name}"}
        try:
            return self.tool_dispatch[name](**args)
        except PermissionRequest:
            raise   # 权限请求必须向上传播，由 websocket_server 捕获并推送卡片
        except TypeError as e:
            return {"error": f"工具参数错误: {e}"}
        except Exception as e:
            return {"error": f"工具执行异常: {e}"}

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
        return result + tail

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

    def _log(self, session_id: str, event: str, data: dict):
        log_file = self.log_dir / f"{self.name}-{datetime.now().strftime('%Y%m%d')}.jsonl"
        record = {"session_id": session_id, "timestamp": datetime.now().isoformat(),
                  "event": event, "agent": self.name, **data}
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    async def _notify_feishu(self, session_id, status, turns, files_changed):
        if not self._feishu_app_id or not self._feishu_app_secret:
            return
        try:
            async with aiohttp.ClientSession() as s:
                r = await s.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={"app_id": self._feishu_app_id, "app_secret": self._feishu_app_secret},
                    timeout=aiohttp.ClientTimeout(total=10))
                token = (await r.json()).get("tenant_access_token", "")
                if not token:
                    return
                emoji = "✅" if status == "completed" else "⚠️"
                text = (f"{emoji} {self.name} {status}\n"
                        f"会话: {session_id}\n轮数: {turns}\n"
                        f"文件:\n" + "\n".join(f"• {f}" for f in files_changed[:5]))
                await s.post(
                    "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"receive_id": self._feishu_chat_id, "msg_type": "text",
                          "content": json.dumps({"text": text})},
                    timeout=aiohttp.ClientTimeout(total=10))
        except Exception:
            pass
