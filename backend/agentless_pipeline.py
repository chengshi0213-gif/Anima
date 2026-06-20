#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agentless_pipeline.py — Phase D 确定性三段管道（v1.3）

对"良定义的单点修复"任务，走固定管道代替开放 agent 循环：
  Stage 1 Locate  — locate_relevant 找候选文件（无 API 调用）
  Stage 2 Patch   — 一次 LLM 调用：文件上下文 + 任务描述 → JSON 补丁
  Stage 3 Verify  — run_verification → 自修复 ≤ max_repair_rounds

对比开放循环的优势（弱模型视角）：
  - 无法"迷路"：不开放工具调用循环，路径确定
  - Token 约 1/5（无多轮 tool_use）
  - 可重现：同任务两次跑结果一致

触发方式：executor 任务前缀 "agentless: <任务>"
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp

sys.path.insert(0, str(Path(__file__).parent))
from code_index import locate_relevant
from verify_gate import run_verification, summarize_failure
from xi_worker import _edit_file, _write_file, _read_file


# ── 结果类型 ──────────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """AgentlessPipeline.run() 的返回值。"""
    status: str                            # completed / unverified / failed / no_files
    summary: str                           # 人读的摘要
    changes_applied: list[dict] = field(default_factory=list)
    rounds: int = 0
    located_files: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "summary": self.summary,
            "changes_applied": self.changes_applied,
            "rounds": self.rounds,
            "located_files": self.located_files,
            "error": self.error,
        }


# ── 单次 LLM 调用 ─────────────────────────────────────────────────────────────

async def _chat_once(messages: list[dict], api_key: str,
                     base_url: str, model_id: str,
                     timeout: int = 120) -> str:
    """单轮 LLM 对话（无工具循环）。返回模型文本。"""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 4096,
    }
    timeout_obj = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_obj) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
    return data["choices"][0]["message"]["content"]


# ── Patch 格式 ────────────────────────────────────────────────────────────────

_PATCH_SCHEMA = """\
输出 JSON（不含 markdown 代码块，不含多余文字）：
{
  "changes": [
    {"file": "相对路径", "old": "要替换的精确原文（含换行/缩进）", "new": "替换成这个"},
    ...
  ],
  "explanation": "一句话说明改了什么"
}

约束：
- file 用相对于项目根的路径
- old 必须在文件中精确存在（用于 file_edit）；新建文件时 old 为 ""
- changes 可有多条（跨文件修改）
"""

_MAX_FILE_CHARS = 8000


def _parse_patch(text: str) -> list[dict]:
    """从模型输出里提取 JSON patch，容忍 markdown 代码块包裹。"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
        return data.get("changes", [])
    except json.JSONDecodeError:
        m2 = re.search(r"\{[\s\S]+\}", text)
        if m2:
            try:
                data = json.loads(m2.group(0))
                return data.get("changes", [])
            except Exception:
                pass
    return []


def _apply_changes(changes: list[dict], root: str) -> list[dict]:
    """把 patch 改动应用到磁盘。返回每条改动的应用结果（含可能的 _error）。"""
    applied: list[dict] = []
    for c in changes:
        fpath = str(Path(root) / c["file"])
        old = c.get("old", "")
        new = c.get("new", "")
        if old == "":
            result = _write_file(fpath, new)
        else:
            result = _edit_file(fpath, old, new, False)
        if "error" in result:
            applied.append({**c, "_error": result["error"]})
        else:
            applied.append(c)
    return applied


# ── Prompt 构建 ───────────────────────────────────────────────────────────────

def _build_patch_messages(task: str, located: list[dict], root: str) -> list[dict]:
    """构建 Stage 2 的 messages（system + user）。"""
    file_blocks: list[str] = []
    for item in located:
        fpath = Path(root) / item["rel"]
        try:
            content = fpath.read_text("utf-8", errors="replace")
            if len(content) > _MAX_FILE_CHARS:
                content = content[:_MAX_FILE_CHARS] + "\n...(截断)"
            file_blocks.append(f"## {item['rel']}\n```\n{content}\n```")
        except OSError:
            pass

    files_text = "\n\n".join(file_blocks) or "（未能读取相关文件内容）"
    user = f"任务：{task}\n\n相关文件：\n\n{files_text}\n\n{_PATCH_SCHEMA}"
    return [
        {"role": "system", "content": "你是专业代码修复工程师。给定任务描述和相关文件，输出精确的 JSON 修复补丁。"},
        {"role": "user", "content": user},
    ]


def _build_repair_messages(task: str, last_changes: list[dict],
                           failure: str, round_n: int) -> list[dict]:
    """修复轮的 messages：任务 + 上一轮改动 + 失败信息。"""
    changes_text = json.dumps(last_changes, ensure_ascii=False, indent=2)
    user = (
        f"任务：{task}\n\n"
        f"上一轮改动（第 {round_n} 轮）：\n```json\n{changes_text}\n```\n\n"
        f"测试失败：\n{failure}\n\n"
        f"请输出新的 JSON 补丁修正错误。{_PATCH_SCHEMA}"
    )
    return [
        {"role": "system", "content": "你是专业代码修复工程师。上一轮修复没有通过测试，请根据失败信息修正。"},
        {"role": "user", "content": user},
    ]


# ── 主管道 ────────────────────────────────────────────────────────────────────

class AgentlessPipeline:
    """固定三段管道：Locate → Patch → Verify。"""

    def __init__(self, api_key: str, base_url: str, model_id: str,
                 max_repair_rounds: int = 3, top_k: int = 8):
        self.api_key = api_key
        self.base_url = base_url
        self.model_id = model_id
        self.max_repair_rounds = max_repair_rounds
        self.top_k = top_k

    async def run(self, task: str, root: str,
                  verify_cmd: str | None = None) -> PipelineResult:
        """
        task:       任务描述
        root:       项目根目录（绝对路径）
        verify_cmd: 验证命令（None = run_verification 自动探测）
        """
        # Stage 1: Locate
        located = locate_relevant(task, root, top_k=self.top_k)
        if not located:
            return PipelineResult(
                status="no_files",
                summary=(
                    "locate_relevant 未找到相关文件，"
                    "任务可能需要新建文件或描述中缺少关键词"
                ),
            )

        # Stage 2: Patch（一次 LLM 调用）
        messages = _build_patch_messages(task, located, root)
        try:
            raw = await _chat_once(
                messages, self.api_key, self.base_url, self.model_id)
        except Exception as exc:
            return PipelineResult(
                status="failed",
                summary=f"Stage 2 LLM 调用失败: {exc}",
                located_files=[item["rel"] for item in located],
                error=str(exc),
            )

        changes = _parse_patch(raw)
        if not changes:
            return PipelineResult(
                status="failed",
                summary=f"模型未输出有效 JSON 补丁\n原始输出(前500字):\n{raw[:500]}",
                located_files=[item["rel"] for item in located],
            )

        applied = _apply_changes(changes, root)
        all_applied: list[dict] = list(applied)
        last_changes = applied
        last_vr: dict = {}

        # Stage 3: Verify + self-repair
        for round_n in range(self.max_repair_rounds + 1):
            last_vr = await asyncio.to_thread(run_verification, root, verify_cmd)
            if last_vr.get("ok"):
                return PipelineResult(
                    status="completed",
                    summary=f"✅ 第 {round_n + 1} 轮验证通过",
                    changes_applied=all_applied,
                    rounds=round_n + 1,
                    located_files=[item["rel"] for item in located],
                )

            if round_n >= self.max_repair_rounds:
                break

            # 修复轮：带失败信息再调一次 LLM
            failure = summarize_failure(
                last_vr.get("stdout", ""),
                last_vr.get("stderr", ""),
                max_lines=30,
            )
            repair_msgs = _build_repair_messages(task, last_changes, failure, round_n + 1)
            try:
                repair_raw = await _chat_once(
                    repair_msgs, self.api_key, self.base_url, self.model_id)
            except Exception:
                break

            new_changes = _parse_patch(repair_raw)
            if not new_changes:
                break

            last_changes = _apply_changes(new_changes, root)
            all_applied.extend(last_changes)

        failure_summary = summarize_failure(
            last_vr.get("stdout", ""),
            last_vr.get("stderr", ""),
            max_lines=20,
        )
        return PipelineResult(
            status="unverified",
            summary=(
                f"经 {min(round_n + 1, self.max_repair_rounds + 1)} 轮仍未通过验证\n\n"
                f"最后失败:\n{failure_summary}"
            ),
            changes_applied=all_applied,
            rounds=min(round_n + 1, self.max_repair_rounds + 1),
            located_files=[item["rel"] for item in located],
        )


# ── 便利工厂：从 MODEL_REGISTRY 解析 ─────────────────────────────────────────

def make_agentless(model_name: str = "DeepSeek-V4-Pro",
                   max_repair_rounds: int = 3) -> AgentlessPipeline:
    """按显示名从 MODEL_REGISTRY 取 API 参数，构建 AgentlessPipeline。"""
    from agent_base import MODEL_REGISTRY
    entry = MODEL_REGISTRY.get(model_name)
    if not entry:
        raise ValueError(f"未知模型: {model_name}")
    key_fn, base_url, model_id = entry
    api_key = key_fn()
    if not api_key:
        raise ValueError(f"模型 {model_name} 的 API key 未配置")
    return AgentlessPipeline(
        api_key=api_key,
        base_url=base_url,
        model_id=model_id,
        max_repair_rounds=max_repair_rounds,
    )
