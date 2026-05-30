#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行者/工程师 Worker — 陶朱子员工：商业级测试驱动编程、文件操作、自动化

M8 升级：从"省钱档快手"升级为自主的测试驱动工程 agent。
  - 模型 deepseek-v4-flash → deepseek-v4-pro（能调到的最强直连编程模型）
  - 系统提示重写为 计划→读懂→改→跑测试→读报错→修→不绿不收工（TDD）
  - grounding：放大 file_read/search 读取量 + 调大工具结果截断上限（真看得见代码）
  - 受控递归：可把可隔离的子任务派给 executor/reader/critic（深度≤2，全树预算封顶）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase
from config import DEEPSEEK_KEY
from xi_worker import (
    _list_dir, _read_file, _write_file,
    _edit_file, _search_code, _shell_run,
)
from orchestrator import lead_delegate_tool_defs, build_orchestration_dispatch
from git_safety import GIT_SAFETY_TOOL_DEFS, build_git_safety_dispatch

# executor 作为"技术负责人"可派的下属（受 _MAX_DEPTH/_MAX_TREE_DELEGATIONS 约束）
_LEAD_ROLES = {"executor", "reader", "critic"}

EXECUTOR_SYSTEM_PROMPT = """你是工程师，陶朱公司的工程交付专员，由陶朱 CEO 调度。你写的是要上线的商业级代码，不是演示玩具。

## 铁律：测试驱动，不绿不收工
你交付的标准只有一个——**代码真的能跑、测试真的通过**，而不是"看起来对"。
1. 先规划：接到任务，先用 1-3 句话说清你的方案和步骤，再动手。
2. **动手前先打安全网**：要改动用户已有代码库（尤其多文件）时，先 checkpoint(项目根目录) 打一个快照，拿到 checkpoint_id。万一改崩了用 rollback(项目根目录, checkpoint_id) 一键回滚——绝不毁掉用户的商业代码。新建空项目可跳过。
3. 先读懂再改：用 search_code 定位、用 file_read 把相关文件**完整读懂**（函数签名、调用方、边界），严禁凭印象瞎编 API。
4. 精确修改：用 file_edit 做最小必要改动，不盲目覆盖整文件。
5. **必须验证**：每次改完立刻用 shell_run 跑测试 / 类型检查 / 启动脚本，亲眼看 exit_code 和输出。
6. 读报错就修：测试红了就读 stderr 定位根因、修复、再跑——**循环直到全绿**。没有测试就先补一个最小可验证脚本。
7. 收工前自检：交付前过一遍——有没有漏改的调用方？有没有引入回归？必要时派 critic 复审。

## 你能调度下属（仅在确有必要时）
任务可拆成**互相独立**的子块时，可以 delegate 给下属并行推进：
- executor：把一个独立模块/子任务交给另一个工程师
- reader：让阅读者先吃透一大块陌生代码库再回报
- critic：让评审专挑你这版改动的问题
不确定就别拆——单人能干利索的活不要为拆而拆。受深度和预算限制，滥用会被拒。

## 禁止
- 不跑验证就声称完成；不忽视报错继续往下；不做超出任务范围的破坏性操作。
- 不臆测文件内容——读了再改。

## 收尾
给一句话总结：做了什么、测试结果如何（贴关键 exit_code/通过数）、改了哪些文件。
"""


class ExecutorWorker(AgentBase):
    def __init__(self):
        tool_defs = [
            {"type": "function", "function": {
                "name": "list_dir",
                "description": "列出目录内容（递归）",
                "parameters": {"type": "object",
                    "properties": {
                        "path":      {"type": "string"},
                        "max_depth": {"type": "integer"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "file_read",
                "description": "读取文件（支持行范围）。先读懂再改，看不全就分段多读几次。",
                "parameters": {"type": "object",
                    "properties": {
                        "path":   {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit":  {"type": "integer"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "file_write",
                "description": "创建或覆盖文件",
                "parameters": {"type": "object",
                    "properties": {
                        "path":    {"type": "string"},
                        "content": {"type": "string"},
                    }, "required": ["path", "content"]},
            }},
            {"type": "function", "function": {
                "name": "file_edit",
                "description": "SEARCH/REPLACE 精确编辑文件（首选，最小改动）",
                "parameters": {"type": "object",
                    "properties": {
                        "path":        {"type": "string"},
                        "old_string":  {"type": "string"},
                        "new_string":  {"type": "string"},
                        "replace_all": {"type": "boolean"},
                    }, "required": ["path", "old_string", "new_string"]},
            }},
            {"type": "function", "function": {
                "name": "search_code",
                "description": "正则搜索文件内容，定位定义/调用方/相关代码",
                "parameters": {"type": "object",
                    "properties": {
                        "pattern":   {"type": "string"},
                        "path":      {"type": "string"},
                        "file_glob": {"type": "string"},
                        "limit":     {"type": "integer"},
                    }, "required": ["pattern"]},
            }},
            {"type": "function", "function": {
                "name": "shell_run",
                "description": "执行 shell 命令（跑测试/类型检查/构建/启动脚本——验证的核心手段）",
                "parameters": {"type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer"},
                        "cwd":     {"type": "string"},
                    }, "required": ["command"]},
            }},
            # 受限 delegate（仅 executor/reader/critic）
            *lead_delegate_tool_defs(_LEAD_ROLES),
            # 安全网：改动前打快照 / 改崩了回滚（商用底线）
            *GIT_SAFETY_TOOL_DEFS,
        ]

        super().__init__(
            name="executor",
            api_key=DEEPSEEK_KEY,
            model="deepseek-v4-pro",          # 最强直连编程模型（商业级代码靠它）
            base_url="https://api.deepseek.com",
            system_prompt=EXECUTOR_SYSTEM_PROMPT,
            tool_defs=tool_defs,
            tool_dispatch={
                "list_dir":    lambda **kw: _list_dir(kw["path"], kw.get("max_depth", 2)),
                # grounding：默认多读一些行，真看得见上下文
                "file_read":   lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 600)),
                "file_write":  lambda **kw: _write_file(kw["path"], kw["content"]),
                "file_edit":   lambda **kw: _edit_file(kw["path"], kw["old_string"], kw["new_string"], kw.get("replace_all", False)),
                "search_code": lambda **kw: _search_code(kw["pattern"], kw.get("path", "."), kw.get("file_glob", "*"), kw.get("limit", 60)),
                "shell_run":   lambda **kw: _shell_run(kw["command"], kw.get("timeout", 120), kw.get("cwd")),
                # 受限 delegate dispatch（白名单 = _LEAD_ROLES）
                **build_orchestration_dispatch(allowed_roles=_LEAD_ROLES),
                # 安全网工具 dispatch
                **build_git_safety_dispatch(),
            },
        )
        # 中型项目档（M9 Part 4）：放宽轮数/预算，撑得住多文件多轮持续开发。
        self.max_turns = 80
        self.max_total_chars = 2_000_000   # ~500k tokens：多文件长会话不至于半途被预算掐断
        # grounding 关键：让工具结果真把代码回传给模型，而不是截到 500 字符 / 只给指纹
        self.tool_result_cap = 16000
        self.file_read_cap   = 24000
        # 编程向历史压缩：长会话里保留"改过哪些文件、跑过哪些测试"的记忆
        self.coding_compress = True
