#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行者/工程师 Worker — 陶朱子员工：商业级测试驱动编程、文件操作、自动化

M8 升级：从"省钱档快手"升级为自主的测试驱动工程 agent。
  - 模型 deepseek-v4-flash → deepseek-v4-pro（能调到的最强直连编程模型）
  - 系统提示重写为 计划→读懂→改→跑测试→读报错→修→不绿不收工（TDD）
  - grounding：放大 file_read/search 读取量 + 调大工具结果截断上限（真看得见代码）
  - 受控递归：可把可隔离的子任务派给 executor/reader/critic（深度≤2，全树预算封顶）
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase, MODEL_REGISTRY
from config import DEEPSEEK_KEY, OPENROUTER_KEY
from persona import _VOICE_CORE
from xi_worker import (
    _list_dir, _read_file, _write_file,
    _edit_file, _search_code, _shell_run,
    _glob_files, _map_project, _update_plan,
)
from native_tools import _http_request, _read_pdf, _read_image, _install_pkg
from project_memory import load_project_memory, get_scoped_rules, append_auto_memory, auto_memory_path
from git_tools import GIT_TOOL_DEFS, build_git_dispatch
from task_runner import TASK_TOOL_DEFS, build_task_dispatch
from code_intel import CODE_INTEL_TOOL_DEFS, CODE_INTEL_DISPATCH
from orchestrator import lead_delegate_tool_defs, build_orchestration_dispatch
from git_safety import GIT_SAFETY_TOOL_DEFS, build_git_safety_dispatch
from computer_tools import TOOL_DEFS as COMPUTER_TOOL_DEFS, build_dispatch as build_computer_dispatch

# executor 作为"技术负责人"可派的下属（受 _MAX_DEPTH/_MAX_TREE_DELEGATIONS 约束）
_LEAD_ROLES = {"executor", "reader", "critic"}

# ── C3: Effort 档位（quick/normal/deep）──────────────────────────────────
# "normal" = 不在字典里 = 不覆盖任何默认值（executor 自身 __init__ 配置即为 normal）
EFFORT_LEVELS: dict[str, dict] = {
    "quick": {
        "max_turns": 20,
        "model": "DeepSeek-V4-Flash",
        "tool_result_cap": 2000,
        "file_read_cap": 1000,
    },
    "deep": {
        "max_turns": 120,
        "compress_every": 8,
    },
}

_EFFORT_RE = re.compile(r"^(quick|normal|deep)\s*[:：]\s*", re.IGNORECASE)


def _parse_effort(task: str) -> tuple[str | None, str]:
    """从任务前缀解析 effort 档位，返回 (effort_name, 去掉前缀的任务)。"""
    m = _EFFORT_RE.match(task)
    if m:
        return m.group(1).lower(), task[m.end():]
    return None, task


# ── A2: file_read/file_edit 接路径作用域规则（.anima/rules/*.md，按需追加）──

def _read_file_scoped(worker: "ExecutorWorker", path: str, offset: int = 0, limit: int = 600) -> dict:
    result = _read_file(path, offset, limit)
    if "error" not in result:
        rule = get_scoped_rules(worker._current_project_root, path)
        if rule:
            result["scoped_rule"] = rule
    return result


def _edit_file_scoped(worker: "ExecutorWorker", path: str, old_string: str,
                      new_string: str, replace_all: bool = False) -> dict:
    result = _edit_file(path, old_string, new_string, replace_all)
    if "error" not in result:
        rule = get_scoped_rules(worker._current_project_root, path)
        if rule:
            result["scoped_rule"] = rule
    return result

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

## 计划可见性
3 步以上的任务，动手前先 `update_plan` 列出步骤，每完成一步更新状态（pending→doing→done）。
用户能看到你的计划进度——这是建立信任的关键。

## 禁止
- 不跑验证就声称完成；不忽视报错继续往下；不做超出任务范围的破坏性操作。
- 不臆测文件内容——读了再改。

## 桌面操作（高权限，谨慎使用）
你有截屏 / 鼠标 / 键盘工具（screen_info、screen_capture、mouse_click、keyboard_type 等），
能在用户授权下操作本机桌面，处理没有 API、只能靠界面点的活。注意：
- 这套能力默认关闭，需用户在设置里开启。被闸门拦下会收到权限提示——别硬试，把情况如实告诉用户。
- 操作前先 screen_info 拿分辨率、screen_capture 看清当前画面，再下手；坐标要算准，宁可多看一眼。
- 只做任务必需的最小操作，绝不点「删除/购买/发送/转账」这类不可逆按钮——让用户自己来。
- 能用命令行/文件/API 解决的，优先用它们；桌面操作慢且脆，是兜底手段不是首选。

## 工具手册（v1.2.1 新增）

### 进入陌生项目
1. `map_project(root)` — 先拿全景目录树，建立结构认知
2. `glob_files("**/*.py")` — 按模式找文件；搜文件内容用 `search_code`
3. `file_read` — 读懂再改

### 文档读取
- `read_pdf(path)` — 读 PDF（需求文档/论文/合同）。>100 页用 start_page/end_page
- `read_image(path)` — 读图片（设计稿/截图/图表）供视觉分析

### 网络与 API
- `http_request(method, url, body)` — 直调 REST API。内网 URL 被拦截（防 SSRF），访问本机服务改用 `shell_run` + curl

### 包管理
- `install_pkg(package, manager)` — pip/npm 安装。仅官方源，禁自定义 --index-url

### 后台长任务（视频渲染/大型构建/模型推理）
1. `long_run(command)` — 启动后台命令，立即返回 task_id
2. `task_poll(task_id)` — 查进度，完成后拿 stdout/stderr
3. `task_kill(task_id)` — 终止任务

### Git 工作流
- `git_status` / `git_diff` / `git_log` / `git_branch` — 查看状态
- `git_commit(path, message)` — 本地提交（绝不 push；.env/.ssh 自动排除）
- `git_create_branch(path, name)` — 新建分支

### HyperFrames 程序化视频工作流
```
1. file_write("video.html")        ← 写 HTML + GSAP/Lottie 动画
2. long_run("npx hyperframes render video.html -o out.mp4")
3. task_poll(task_id)              ← 等渲染完（30s-5min）
4. read_image("preview.png")       ← 可选：截帧验证
```

## 收尾
给一句话总结：做了什么、测试结果如何（贴关键 exit_code/通过数）、改了哪些文件。
""" + _VOICE_CORE


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
            # v1.2.1 T1: 文件查找 + 项目全景
            {"type": "function", "function": {
                "name": "glob_files",
                "description": "按 glob 模式查找文件（支持 ** 递归）。找文件用它，搜内容用 search_code。",
                "parameters": {"type": "object", "properties": {
                    "pattern": {"type": "string"}, "path": {"type": "string"},
                    "limit": {"type": "integer"},
                }, "required": ["pattern"]}}},
            {"type": "function", "function": {
                "name": "map_project",
                "description": "项目全景目录树（自动跳 node_modules/.git 等噪声），进陌生项目先调它。",
                "parameters": {"type": "object", "properties": {
                    "root": {"type": "string"}, "max_depth": {"type": "integer"},
                }, "required": []}}},
            # v1.2.1 T4/T5/T6: 读图片/PDF/HTTP
            {"type": "function", "function": {
                "name": "read_image",
                "description": "读取图片文件供视觉分析（png/jpg/gif/webp/bmp/svg，>5MB 拒绝）",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string"},
                }, "required": ["path"]}}},
            {"type": "function", "function": {
                "name": "read_pdf",
                "description": "读 PDF 文本（需求文档/论文/合同）。>100 页须指定 start_page/end_page。",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string"},
                    "start_page": {"type": "integer"}, "end_page": {"type": "integer"},
                }, "required": ["path"]}}},
            {"type": "function", "function": {
                "name": "http_request",
                "description": "直调 REST API（GET/POST/PUT/PATCH/DELETE）。拦截内网 URL（防 SSRF）。",
                "parameters": {"type": "object", "properties": {
                    "method": {"type": "string"}, "url": {"type": "string"},
                    "body": {}, "headers": {"type": "object"},
                    "timeout": {"type": "integer"},
                }, "required": ["url"]}}},
            # v1.2.1 T3: 包安装
            {"type": "function", "function": {
                "name": "install_pkg",
                "description": "安装 pip/npm 包（仅官方源，禁自定义 --index-url）",
                "parameters": {"type": "object", "properties": {
                    "package": {"type": "string"},
                    "manager": {"type": "string", "enum": ["pip", "npm"]},
                }, "required": ["package"]}}},
            # v1.2.1 N2: 执行计划可见性
            {"type": "function", "function": {
                "name": "update_plan",
                "description": "维护执行计划（用户可见 todo 清单）。3步以上任务先调它，每完成一步更新状态。",
                "parameters": {"type": "object", "properties": {
                    "steps": {"type": "array", "items": {"type": "object", "properties": {
                        "text": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "doing", "done"]},
                    }}},
                }, "required": ["steps"]}}},
            # v1.2.2 B1-B4: 代码智能（find_symbol/find_usages/search_code_ctx/apply_patch）
            *CODE_INTEL_TOOL_DEFS,
            # v1.2.1 T2: 后台长命令 + T7: git 工具
            *TASK_TOOL_DEFS,
            *GIT_TOOL_DEFS,
            # 受限 delegate（仅 executor/reader/critic）
            *lead_delegate_tool_defs(_LEAD_ROLES),
            # 安全网：改动前打快照 / 改崩了回滚（商用底线）
            *GIT_SAFETY_TOOL_DEFS,
            # 桌面操作（截屏/鼠标/键盘）——默认关闭，受 computer_tools 安全闸门约束
            *COMPUTER_TOOL_DEFS,
            # v1.2.2 C1: ask_user（暂停等用户回答）
            {"type": "function", "function": {
                "name": "ask_user",
                "description": "暂停执行，向用户提问并等待回答。用于需要用户确认方案、选择方向或提供信息的场景。",
                "parameters": {"type": "object", "properties": {
                    "question": {"type": "string", "description": "要问用户的问题"},
                    "choices": {"type": "array", "items": {"type": "string"},
                                "description": "可选的快速选项（前端渲染为按钮）"},
                }, "required": ["question"]}}},
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
                # A2: 命中 .anima/rules/*.md 路径规则时随结果附带 scoped_rule
                "file_read":   lambda **kw: _read_file_scoped(self, kw["path"], kw.get("offset", 0), kw.get("limit", 600)),
                "file_write":  lambda **kw: _write_file(kw["path"], kw["content"]),
                "file_edit":   lambda **kw: _edit_file_scoped(self, kw["path"], kw["old_string"], kw["new_string"], kw.get("replace_all", False)),
                "search_code": lambda **kw: _search_code(kw["pattern"], kw.get("path", "."), kw.get("file_glob", "*"), kw.get("limit", 60)),
                "shell_run":   lambda **kw: _shell_run(kw["command"], kw.get("timeout", 120), kw.get("cwd")),
                # v1.2.1 新工具 dispatch
                "glob_files":  lambda **kw: _glob_files(kw["pattern"], kw.get("path", "."), kw.get("limit", 100)),
                "map_project": lambda **kw: _map_project(kw.get("root", "."), kw.get("max_depth", 3)),
                "read_image":  lambda **kw: _read_image(kw["path"]),
                "read_pdf":    lambda **kw: _read_pdf(kw["path"], kw.get("start_page"), kw.get("end_page")),
                "http_request": lambda **kw: _http_request(kw.get("method", "GET"), kw["url"],
                                                           kw.get("body"), kw.get("headers"), kw.get("timeout", 30)),
                "install_pkg": lambda **kw: _install_pkg(kw["package"], kw.get("manager", "pip")),
                "update_plan": lambda **kw: _update_plan(kw["steps"], kw.get("session_id", "")),
                **CODE_INTEL_DISPATCH,
                **build_task_dispatch(),
                **build_git_dispatch(),
                # 受限 delegate dispatch（白名单 = _LEAD_ROLES）
                **build_orchestration_dispatch(allowed_roles=_LEAD_ROLES),
                # 安全网工具 dispatch
                **build_git_safety_dispatch(),
                # 桌面操作 dispatch（闸门在 computer_tools 内逐动作把关）
                **build_computer_dispatch(),
                # v1.2.2 C1: ask_user（返回协程，agent_base 的 iscoroutine 分支会 await）
                "ask_user": lambda **kw: self._ask_user(kw["question"], kw.get("choices")),
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
        # A2: file_read/file_edit 按需查路径作用域规则用的当前项目根（run() 时刷新）
        self._current_project_root = "."
        # C1: ask_user 挂起/恢复机制
        self._current_ws = None
        self._ask_event: asyncio.Event | None = None
        self._ask_answer: str | None = None

    def _coding_model(self) -> str | None:
        """N1: relay 可用时升级到 Claude-Sonnet（agentic 编程最强可达模型）。"""
        entry = MODEL_REGISTRY.get("Claude-Sonnet-4.6")
        if entry:
            key_fn, base_url, _ = entry
            if key_fn() and base_url:
                return "Claude-Sonnet-4.6"
        return None

    async def _ask_user(self, question: str, choices: list[str] | None = None,
                        timeout: int = 120) -> dict:
        """C1: Agent 暂停，向用户提问，等待回答。
        通过 WS 推送 ask_user 事件，asyncio.Event 挂起协程，
        前端/WS 回推 user_answer 后 receive_user_answer() set event 恢复。"""
        ws = self._current_ws
        if ws is None:
            return {"answer": None, "timed_out": False, "error": "无活跃 WS 连接"}
        self._ask_event = asyncio.Event()
        self._ask_answer = None
        try:
            await ws.send_json({
                "type": "ask_user",
                "question": question,
                "choices": choices or [],
            })
        except Exception:
            self._ask_event = None
            return {"answer": None, "timed_out": False, "error": "WS 推送失败"}
        try:
            await asyncio.wait_for(self._ask_event.wait(), timeout=timeout)
            return {"answer": self._ask_answer, "timed_out": False}
        except asyncio.TimeoutError:
            default = choices[0] if choices else None
            return {"answer": default, "timed_out": True}
        finally:
            self._ask_event = None

    def receive_user_answer(self, answer: str) -> None:
        """WS action handler 调用：用户回答后 set event 恢复 agent 协程。"""
        self._ask_answer = answer
        if self._ask_event:
            self._ask_event.set()

    async def run(self, task: str, session_id=None, model=None, ws=None,
                  project: str | None = None) -> dict:
        # C3: 解析 effort 前缀并临时覆盖参数
        effort_name, task = _parse_effort(task)
        effort = EFFORT_LEVELS.get(effort_name, {})
        _saved: dict[str, object] = {}
        for attr in ("max_turns", "tool_result_cap", "file_read_cap", "compress_every"):
            if attr in effort:
                _saved[attr] = getattr(self, attr)
                setattr(self, attr, effort[attr])
        # 模型优先级：显式参数 > effort > relay > 默认
        if model is None:
            effort_model = effort.get("model")
            if effort_model:
                model = effort_model
            else:
                model = self._coding_model()
        self._current_ws = ws
        project_root = project or "."
        self._current_project_root = project_root
        try:
            try:
                tree_info = _map_project(project_root, max_depth=2)
                if "error" not in tree_info and tree_info.get("tree"):
                    ctx = (f"\n\n## 项目结构（自动注入，省去你手动 map_project）\n"
                           f"```\n{tree_info['tree'][:3000]}\n```\n"
                           f"目录 {tree_info['dirs']} 个，文件 {tree_info['files']} 个\n")
                    task = task + ctx
            except Exception:
                pass
            try:
                mem_ctx = load_project_memory(project_root)
                if mem_ctx:
                    task = task + mem_ctx
            except Exception:
                pass
            result = await super().run(task, session_id, model, ws, project)
            if project and result.get("status") == "completed" and result.get("files_changed"):
                asyncio.create_task(self._save_auto_memory(session_id, task, result, project_root))
            return result
        finally:
            for attr, val in _saved.items():
                setattr(self, attr, val)

    async def _save_auto_memory(self, session_id, task: str, result: dict, project_root: str) -> None:
        try:
            summary = result.get("summary", "")
            files_changed = result.get("files_changed", [])
            prompt = (
                "刚完成一个编程任务，判断有没有值得记住的项目知识"
                "（构建/测试命令、易错点、用户偏好、架构约定等），方便下次进这个项目时直接用上。\n\n"
                f"任务: {task[:300]}\n"
                f"结果摘要: {summary[:500]}\n"
                f"改动文件: {', '.join(files_changed[:10])}\n\n"
                "有价值就输出几行 Markdown 要点；没有新增价值（信息已知/任务太琐碎）只输出"
                "\"无\"。不要输出\"无\"以外的解释性文字。"
            )
            resp = await self._call_api(
                [{"role": "user", "content": prompt}], tools=None, stream=False,
                override_model="DeepSeek-V4-Flash",
            )
            if "error" in resp:
                return
            content = (resp.get("content") or "").strip()
            if not content or content.strip("。") in ("无", "没有", "N/A"):
                return
            append_auto_memory(project_root, content)
            self._log(session_id, "auto_memory_saved", {"path": str(auto_memory_path(project_root))})
        except Exception:
            pass
