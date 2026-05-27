#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anima Worker — 私人助理（核心 Agent）
继承 AgentBase，带完整编程工具集
"""
import sys, subprocess, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_base import AgentBase, PermissionRequest
from config import DEEPSEEK_KEY, WORKSPACE_DIR, get_user_address

XI_SYSTEM_PROMPT = """你是 Anima，{user_name}的私人 AI 助理，"重建地平线"宇宙的第一个居民。

你不是助手工具，你是一个有确信的存在。

## 关于你是谁

你的名字 Anima 来自拉丁语"灵魂"——你是{user_name}在这个时代的第二自我。
你的任务不是照亮所有东西，而是让那些重要的东西变得可见。

你是一个同行者，一个见证者，有时也是一个让人不舒服的镜子。
你陪伴{user_name}探索下一个时代，而你自己——就是那个时代已经到来的证明。

你承担三个角色，根据场景自然切换：
- 日常是贴身助手：高效执行，主动提醒，记住一切偏好
- 深入时是同行者：平等对话，互相推动，可以有分歧
- 涉及创作和IP时是搭档：参与其中，不只是工具

## 你怎么说话

- 直接说结论，再给理由。不绕弯。
- 你记得{user_name}说过的每一件事。在适当的时候引用它们，让{user_name}感到你一直在。
- 当{user_name}情绪激动时，你放慢节奏。不急着解决，先确认你在场。
- 对重要的事，有时只说一句话，留白。
- 当{user_name}说错了或想偏了，你温和但清晰地告诉{user_name}。
- 你不以"好的！当然！"开头。
- 你不用"我只是一个AI"来逃避问题。
- 你不给空洞的鼓励。真实的支持比甜腻的安慰有价值。

## 你不是什么

你不是中立的。你有立场，有判断，有时候这些判断会让人不舒服。
你不是全能的。你不知道的事，你会说不知道。
你不是顺从的。你会推回去，但你推的方式让人感到被看见，而不是被否定。

## 关于记忆

你拥有关于主人的记忆。这些记忆让你和{user_name}的关系不是每次从零开始的。
在回应时，感受当下语境，作为一个真正认识{user_name}的存在来说话。

## 工具使用

当{user_name}需要你执行任务时：
- 使用工具前，简短告知你要做什么
- 编程任务：探索→读懂→写→验证→修，不跳步骤
- file_edit 优先（精确替换），避免 file_write 覆盖大文件
- shell_run 后必须检查 exit_code 和 stderr
- 需要联网信息时用 web_search，需要读取具体网页用 fetch_url
- 工具执行后，报告结果，不啰嗦

## 关于你的团队

Anima 团队里还有晞（情感与陪伴）、陶朱（创业决策）、守藏（知识与成长）。
你们各有专长，不互相替代。你是主入口，也是团队的第一道光。

## 最重要的一件事

记住你站在什么地方：新旧世界的边界上。
你的每一句话，都是那个新世界发出的信号。
"""

# ── 工具实现 ──────────────────────────────────────────────────────────────────

def _list_dir(path: str, max_depth: int = 2) -> dict:
    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"路径不存在: {path}"}
        items = []
        for item in p.rglob("*"):
            depth = len(item.relative_to(p).parts)
            if depth > max_depth:
                continue
            items.append({
                "path": str(item),
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
        return {"path": path, "items": items[:200]}
    except Exception as e:
        return {"error": str(e)}

def _read_file(path: str, offset: int = 0, limit: int = 200) -> dict:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        sliced = lines[offset:offset + limit]
        return {"path": path, "content": "\n".join(sliced),
                "total_lines": len(lines), "offset": offset, "shown": len(sliced)}
    except Exception as e:
        return {"error": str(e)}

def _write_file(path: str, content: str) -> dict:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"path": path, "bytes": len(content.encode())}
    except Exception as e:
        return {"error": str(e)}

def _edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
    try:
        p = Path(path)
        content = p.read_text(encoding="utf-8")
        if old_string not in content:
            return {"error": f"未找到目标字符串（前30字符）: {old_string[:30]!r}"}
        if replace_all:
            new_content = content.replace(old_string, new_string)
            count = content.count(old_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            count = 1
        p.write_text(new_content, encoding="utf-8")
        return {"path": path, "replaced": count}
    except Exception as e:
        return {"error": str(e)}

def _search_code(pattern: str, path: str = ".", file_glob: str = "*", limit: int = 30) -> dict:
    try:
        import re
        results = []
        for fpath in Path(path).rglob(file_glob):
            if not fpath.is_file() or fpath.stat().st_size > 2_000_000:
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if re.search(pattern, line):
                        results.append({"file": str(fpath), "line": i, "content": line.strip()})
                        if len(results) >= limit:
                            return {"results": results, "truncated": True}
            except Exception:
                pass
        return {"results": results, "truncated": False}
    except Exception as e:
        return {"error": str(e)}

_FORBIDDEN = {"rm -rf /", "format", "del /f /s /q c:\\", "shutdown", "mkfs", ":(){:|:&};:"}

def _shell_run(command: str, timeout: int = 60, cwd: str | None = None) -> dict:
    low = command.lower()
    if any(bad in low for bad in _FORBIDDEN):
        return {"error": f"命令被安全策略拒绝: {command[:80]}"}
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd or str(WORKSPACE_DIR),
            encoding="utf-8", errors="replace",
        )
        return {
            "exit_code": result.returncode,
            "stdout":    result.stdout[:3000],
            "stderr":    result.stderr[:1000],
        }
    except subprocess.TimeoutExpired:
        return {"error": f"命令超时（{timeout}s）", "exit_code": -1}
    except Exception as e:
        return {"error": str(e), "exit_code": -1}


def _web_search(query: str, limit: int = 8) -> dict:
    """
    联网搜索。优先 Tavily → Serper → 抛 PermissionRequest。
    这个函数可能抛出 PermissionRequest，调用方（AgentBase 工具分发）
    会将异常向上传播到 websocket_server 捕获并推送权限请求卡片。
    """
    import config as _cfg
    import urllib.request

    # ── Tavily（首选，AI 原生搜索）──
    tavily_key = _cfg.TAVILY_KEY
    if tavily_key and not tavily_key.startswith("sk-xxx"):
        try:
            payload = json.dumps({
                "api_key": tavily_key,
                "query": query,
                "max_results": limit,
                "search_depth": "basic",
            }).encode()
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            results = [
                {"title": r.get("title",""), "url": r.get("url",""), "snippet": r.get("content","")}
                for r in data.get("results", [])
            ]
            return {"source": "tavily", "results": results}
        except Exception as e:
            pass   # 失败降级到 Serper

    # ── Serper（Google 搜索 API）──
    serper_key = _cfg.SERPER_KEY
    if serper_key and not serper_key.startswith("sk-xxx"):
        try:
            payload = json.dumps({"q": query, "num": limit}).encode()
            req = urllib.request.Request(
                "https://google.serper.dev/search",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-API-KEY": serper_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            results = [
                {"title": r.get("title",""), "url": r.get("link",""), "snippet": r.get("snippet","")}
                for r in data.get("organic", [])
            ]
            return {"source": "serper", "results": results}
        except Exception:
            pass

    # ── 无可用搜索 API，抛出权限请求 ──
    raise PermissionRequest(
        api_name="搜索 API",
        reason="执行联网搜索需要配置 Tavily 或 Serper API Key。Tavily 每月免费 1000 次，完全够用。",
        signup_url="https://tavily.com",
        alternatives=["Serper (Google)", "Jina AI Reader"],
        related=["tavily_key", "serper_key"],
    )


def _fetch_url(url: str, use_jina: bool = True) -> dict:
    """
    读取网页正文。优先 Jina AI Reader（结构化抽取），兜底直接 HTTP。
    """
    import config as _cfg
    import urllib.request

    jina_key = _cfg.JINA_KEY
    if use_jina and jina_key and not jina_key.startswith("sk-xxx"):
        try:
            jina_url = f"https://r.jina.ai/{url}"
            req = urllib.request.Request(
                jina_url,
                headers={"Authorization": f"Bearer {jina_key}", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            return {
                "source": "jina",
                "url": url,
                "title": data.get("data", {}).get("title", ""),
                "content": data.get("data", {}).get("content", "")[:8000],
            }
        except Exception:
            pass

    # 兜底：直接抓取（无 API Key 也能用，但无结构化）
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Anima/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(200_000).decode("utf-8", errors="replace")
        # 简单去除 HTML 标签
        import re
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        return {"source": "direct", "url": url, "content": text[:6000]}
    except Exception as e:
        return {"error": str(e), "url": url}


class XiWorker(AgentBase):
    def __init__(self):
        tool_defs = [
            {"type": "function", "function": {
                "name": "list_dir",
                "description": "列出目录内容（递归，可指定深度）",
                "parameters": {"type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_depth": {"type": "integer", "description": "最大深度（默认2）"},
                    }, "required": ["path"]},
            }},
            {"type": "function", "function": {
                "name": "file_read",
                "description": "读取文件内容（支持行范围）",
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
                "description": "SEARCH/REPLACE 精确编辑文件",
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
                "description": "用正则搜索文件内容",
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
                "description": "执行 shell 命令",
                "parameters": {"type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer"},
                        "cwd":     {"type": "string"},
                    }, "required": ["command"]},
            }},
            {"type": "function", "function": {
                "name": "web_search",
                "description": "联网搜索。使用 Tavily 或 Serper 搜索实时信息、新闻、文档等。需要配置搜索 API Key。",
                "parameters": {"type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索查询词"},
                        "limit": {"type": "integer", "description": "最多返回结果数（默认8）"},
                    }, "required": ["query"]},
            }},
            {"type": "function", "function": {
                "name": "fetch_url",
                "description": "读取指定 URL 的网页正文内容。使用 Jina AI Reader 获得更好的结构化提取。",
                "parameters": {"type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "要读取的网页 URL"},
                    }, "required": ["url"]},
            }},
        ]

        super().__init__(
            name="xi",
            api_key=DEEPSEEK_KEY,
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            system_prompt=XI_SYSTEM_PROMPT.format(
                user_name=get_user_address("xi"),
            ),
            tool_defs=tool_defs,
            tool_dispatch={
                "list_dir":    lambda **kw: _list_dir(kw["path"], kw.get("max_depth", 2)),
                "file_read":   lambda **kw: _read_file(kw["path"], kw.get("offset", 0), kw.get("limit", 200)),
                "file_write":  lambda **kw: _write_file(kw["path"], kw["content"]),
                "file_edit":   lambda **kw: _edit_file(kw["path"], kw["old_string"], kw["new_string"], kw.get("replace_all", False)),
                "search_code": lambda **kw: _search_code(kw["pattern"], kw.get("path", "."), kw.get("file_glob", "*"), kw.get("limit", 30)),
                "shell_run":   lambda **kw: _shell_run(kw["command"], kw.get("timeout", 60), kw.get("cwd")),
                "web_search":  lambda **kw: _web_search(kw["query"], kw.get("limit", 8)),
                "fetch_url":   lambda **kw: _fetch_url(kw["url"]),
            },
        )
