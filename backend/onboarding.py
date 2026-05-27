#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
onboarding.py — 新用户首次体验（FTUE）

当用户完成 Onboarding 设置后，Anima 自动发送第一条欢迎消息。
包含：自我介绍、能力简介、第一个引导任务建议。
"""
import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path.home() / ".anima" / "data"
FTUE_FLAG = DATA_DIR / "ftue_done.json"


def is_ftue_done() -> bool:
    return FTUE_FLAG.exists()


def mark_ftue_done(agent_names: dict = None):
    FTUE_FLAG.parent.mkdir(parents=True, exist_ok=True)
    FTUE_FLAG.write_text(json.dumps({
        "done_at": datetime.now().isoformat(),
        "agent_names": agent_names or {},
    }, ensure_ascii=False), "utf-8")


# 固定名称，不再从 agent_names 读取（名称由系统决定，不可用户修改）
_FIXED_NAMES = {
    "xi":       "Anima",
    "yiyi":     "晞",
    "tianyuan": "陶朱",
    "shoucang": "守藏",
}

def get_welcome_message(agent_names: dict = None, lang: str = "zh") -> str:
    """生成 Anima 第一条欢迎消息（不依赖 LLM，纯模板）"""
    # agent_names 参数保留兼容性，但实际使用固定名称
    anima_name    = _FIXED_NAMES["xi"]
    xi_name       = _FIXED_NAMES["yiyi"]
    taozu_name    = _FIXED_NAMES["tianyuan"]
    shoucang_name = _FIXED_NAMES["shoucang"]

    return f"""嗨，很高兴认识你！我是 **{anima_name}**，你的私人 AI 助理。

我们这里有四位核心伙伴：

- **{anima_name}**（就是我）— 处理日常任务，文件、代码、信息搜索都行
- **{xi_name}** — 情感陪伴，倾听你的心情，帮你理清思路
- **{taozu_name}** — 创业者助手，带着一支 AI 小团队，专攻复杂任务
- **{shoucang_name}** — 知识管理者，帮你整理 Obsidian 笔记，每天自动更新

**快速开始 3 件事：**
1. 和我聊任何话题，比如 "帮我整理今天的待办事项"
2. 点击左侧「知识&记忆」上传你的项目文档，我就能了解你的工作
3. 去「设置 → API 管理」把你需要的 API 都配好，我的能力会更强

有什么想让我帮忙的吗？😊"""


def get_shoucang_first_run_prompt() -> str:
    """守藏首次运行 SOP 的特殊提示词：建立用户基础档案"""
    return """这是 Anima 系统第一次启动，请执行初始化 SOP：

1. 检查 Vault 目录是否存在并完整，若缺失则补全结构
2. 创建 Memory/USER.md 用户档案模板（包含：基本信息待补充、兴趣偏好待观察、重要事项待记录）
3. 创建 Memory/emotional.md 情感记录模板
4. 创建 Goals/README.md 目标管理说明
5. 在 Daily Notes 创建今天的日记模板
6. 输出：Anima 记忆系统已初始化完成，告知用户 Vault 位置

请执行。"""
