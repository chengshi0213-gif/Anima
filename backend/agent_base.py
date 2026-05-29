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
    QWEN_KEY, KIMI_KEY, GLM_KEY, GEMINI_KEY, OPENROUTER_KEY,
)

# ── 模型注册表：前端显示名 → API 参数 ──────────────────────────────────────
# 格式: display_name → (api_key_var, base_url, api_model_id)
# OpenRouter 作为 Claude/Gemini 的兜底（兼容 OpenAI 协议）
# 中转站地址：可在 config.yaml 中通过 api.relay_url 自定义
def _get_relay():
    try:
        from config import _get as _cfg_get
        url = _cfg_get("api.relay_url", "")
        if url:
            return url.rstrip("/")
    except Exception:
        pass
    return "http://1.95.142.151:3000/v1"

_RELAY = _get_relay()
_DS    = "https://api.deepseek.com"
_QWEN  = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_KIMI  = "https://api.moonshot.cn/v1"

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
                return key, base_url, model_id
        return self.api_key, self.base_url, self.model

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
            delta = chunk.get("choices", [{}])[0].get("delta", {})
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
                get_active_project_context,
            )
            memory_ctx = get_memory_injection(self.name)
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

    def _trim_result(self, tool_name: str, result: dict, seen: set[str]) -> str:
        text = json.dumps(result, ensure_ascii=False)
        h = hashlib.sha256(text.encode()).hexdigest()
        if h in seen:
            return json.dumps({"_dedup": True, "sha256": h[:12]}, ensure_ascii=False)
        seen.add(h)
        # URL 缩短
        text = re.sub(r"https?://[^\s<>\"{}|\\^`\[\]]{20,}",
                      lambda m: f"{m.group(0)[:40]}…", text)
        if tool_name == "file_read" and len(text) > 2048:
            try:
                d = json.loads(text)
                c = d.get("content", "")
                if len(c) > 2048:
                    return json.dumps({"fingerprint": f"[{len(c)}字符 | SHA:{h[:8]}]",
                                       "note": "文件过大已压缩"}, ensure_ascii=False)
            except Exception:
                pass
        return text[:500] + f"…[截断,原长{len(text)}字符]" if len(text) > 500 else text

    def _compress_history(self, messages: list[dict]) -> list[dict]:
        if len(messages) <= 10:
            return messages
        sys_msgs = [m for m in messages if m["role"] == "system"]
        rest = [m for m in messages if m["role"] != "system"]
        first_user = next((m for m in rest if m["role"] == "user"), None)
        tail = rest[-6:] if len(rest) > 6 else rest
        result = sys_msgs[:]
        if first_user and first_user not in tail:
            result.append(first_user)
            result.append({"role": "assistant", "content": "[中间对话已压缩]"})
        return result + tail

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
