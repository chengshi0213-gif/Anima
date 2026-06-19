#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentToolGateMixin — 工具执行咽喉
从 agent_base.py 抽出，独立维护（agent_base 曾因这坨逻辑膨胀到 694 行 > 600 软红线）。

所有工具调用都经此单一咽喉，串成一条固定管道：
    _file_gate（盲改防护） → _guard_tool（钩子/权限/确认） → 派发执行 → _post_tool（后置钩子）

由 AgentBase 继承；依赖 self 上的以下属性/方法：
  self.tool_dispatch   工具名 → 可调用
  self._file_state     dict[path → mtime]，H4 盲改防护用（run() 中初始化）
  self._log            日志（来自 AgentLoggingMixin，本模块不直接用）

PermissionRequest 也定义在此（工具/权限语义同源），agent_base 再 re-export，
外部 `from agent_base import PermissionRequest` 保持不变。
"""
import inspect, os


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


class AgentToolGateMixin:
    """工具执行咽喉的 Mixin，供 AgentBase 继承。"""

    async def _execute_tool(self, name: str, args: dict, ctx: dict | None = None) -> dict:
        """工具调用咽喉：异步化 + 确认/钩子（ctx 不为 None 时） + H4 文件闸门。"""
        if name not in self.tool_dispatch:
            return {"error": f"未知工具: {name}"}
        # H4: Read-before-Edit 硬闸门
        gate = self._file_gate(name, args)
        if gate is not None:
            return gate
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
        # H4: file_read 成功后记录 mtime
        if name == "file_read" and "error" not in result and args.get("path"):
            try:
                self._file_state[args["path"]] = os.path.getmtime(args["path"])
            except OSError:
                pass
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
        # D3: 权限分级（readonly/confirm/acceptEdits/auto + 自定义规则）
        try:
            from permission import check_tool_permission
            verdict = check_tool_permission(name, args)
            if verdict and verdict.startswith("deny:"):
                return {"error": verdict[5:], "cancelled": True}
            if verdict == "confirm":
                from confirm import get_broker
                if not await get_broker().guard("permission_rule", name, args, ctx):
                    return {"error": f"操作被拒绝: {name}", "cancelled": True}
                return None
        except PermissionRequest:
            raise
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

    def _file_gate(self, name: str, args: dict) -> dict | None:
        """H4: file_edit / file_write(已存在文件) 必须先 file_read 过。"""
        if name not in ("file_edit", "file_write"):
            return None
        path = args.get("path", "")
        if not path:
            return None
        if name == "file_write" and not os.path.exists(path):
            return None  # 新文件不需要先读
        if path not in self._file_state:
            return {"error": f"请先 file_read 读取 {path} 再修改（防止盲改）"}
        try:
            current_mtime = os.path.getmtime(path)
            if abs(current_mtime - self._file_state[path]) > 0.01:
                return {"error": f"文件 {path} 在你读过之后被外部修改了，请重新 file_read"}
        except OSError:
            pass
        return None
