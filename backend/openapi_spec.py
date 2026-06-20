#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anima HTTP API — OpenAPI 3.0 规格文档
访问 GET /openapi.json 获取机器可读规格
访问 GET /docs        获取 Swagger UI（内嵌 HTML）
"""
from pathlib import Path
import json

try:
    from config import ANIMA_VERSION as VERSION  # 单一版本真源（R2）
except Exception:
    VERSION = "1.3.0"

SPEC: dict = {
    "openapi": "3.0.3",
    "info": {
        "title": "Anima Agent API",
        "description": (
            "Anima 本地 AI 多 Agent 系统的 HTTP API。\n\n"
            "**Agent WebSocket 接口**（聊天流式输出）在 `/ws/{agent_id}` 端点。\n"
            "**Webhook 触发**（CI/CD / Zapier / n8n）使用 `POST /hook/{agent_id}`。"
        ),
        "version": VERSION,
        "contact": {"name": "xi", "url": "https://github.com/tianyuan-team/anima"},
    },
    "servers": [{"url": "http://localhost:9100", "description": "本地开发服务器"}],
    "tags": [
        {"name": "setup",     "description": "初始化配置 & FTUE"},
        {"name": "agents",    "description": "Agent WebSocket 连接"},
        {"name": "webhook",   "description": "Webhook 外部触发"},
        {"name": "memory",    "description": "用户记忆 & Vault"},
        {"name": "vault",     "description": "Obsidian Vault 文件系统"},
        {"name": "skills",    "description": "Skill 管理"},
        {"name": "reports",   "description": "日报 / 周报"},
        {"name": "scheduler", "description": "定时任务"},
        {"name": "workflow",  "description": "工作流编排"},
        {"name": "shoucang",  "description": "守藏 SOP"},
        {"name": "notifier",  "description": "推送通知渠道"},
        {"name": "config",    "description": "API 配置管理"},
        {"name": "membership", "description": "会员激活 & 权限"},
    ],
    "paths": {
        # ── Setup ──────────────────────────────────────
        "/setup/status": {
            "get": {
                "tags": ["setup"], "summary": "获取配置状态",
                "responses": {
                    "200": {"description": "配置状态", "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "configured": {"type": "boolean"},
                            "ftue_done":  {"type": "boolean"},
                            "agent_names": {"type": "object"},
                        }
                    }}}}
                }
            }
        },
        "/setup/save": {
            "post": {
                "tags": ["setup"], "summary": "保存初始配置",
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "api":          {"type": "object", "description": "API Keys 字典"},
                        "agent_names":  {"type": "object", "description": "Agent 昵称"},
                        "vault_dir":    {"type": "string"},
                        "lang":         {"type": "string", "enum": ["zh", "en"]},
                    },
                    "required": ["api"],
                }}}},
                "responses": {"200": {"description": "ok"}}
            }
        },
        "/setup/complete": {
            "post": {
                "tags": ["setup"], "summary": "完成 FTUE，返回欢迎语并触发守藏初始化",
                "responses": {"200": {"description": "返回欢迎消息", "content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "ok":              {"type": "boolean"},
                        "welcome_message": {"type": "string"},
                        "first_run":       {"type": "boolean"},
                    }
                }}}}}
            }
        },
        # ── Agents ─────────────────────────────────────
        "/ws/{agent_id}": {
            "get": {
                "tags": ["agents"], "summary": "WebSocket 聊天接口",
                "parameters": [{"name": "agent_id", "in": "path", "required": True,
                                "schema": {"type": "string",
                                           "enum": ["xi","yiyi","tianyuan","shoucang",
                                                    "executor","writer","reader","critic"]}}],
                "responses": {"101": {"description": "WebSocket 协议升级成功"}}
            }
        },
        # ── Webhook ────────────────────────────────────
        "/hook/{agent_id}": {
            "post": {
                "tags": ["webhook"], "summary": "外部 Webhook 触发 Agent 任务",
                "description": "供 CI/CD、Zapier、n8n 等调用。异步模式立即返回 202，同步模式等待结果（最长 120s）。",
                "parameters": [{"name": "agent_id", "in": "path", "required": True,
                                "schema": {"type": "string"}}],
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "prompt":         {"type": "string", "description": "发给 Agent 的指令"},
                        "token":          {"type": "string", "description": "Webhook 鉴权 token（可选）"},
                        "context":        {"type": "string", "description": "附加上下文"},
                        "return_result":  {"type": "boolean", "default": False,
                                           "description": "是否等待结果同步返回"},
                    },
                    "required": ["prompt"],
                }}}},
                "responses": {
                    "202": {"description": "后台触发成功"},
                    "200": {"description": "同步结果（return_result=true）"},
                    "403": {"description": "token 无效"},
                }
            }
        },
        # ── Memory ─────────────────────────────────────
        "/memory/learn": {
            "post": {
                "tags": ["memory"], "summary": "让 Anima 记住一件事",
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "key":   {"type": "string", "description": "这是关于什么"},
                        "value": {"type": "string", "description": "具体内容"},
                        "agent": {"type": "string", "default": "xi"},
                    },
                    "required": ["key", "value"],
                }}}},
                "responses": {"200": {"description": "写入成功"}}
            }
        },
        # ── Vault ──────────────────────────────────────
        "/vault/tree": {
            "get": {"tags": ["vault"], "summary": "获取 Vault 文件树",
                    "responses": {"200": {"description": "文件树 JSON"}}}
        },
        "/vault/file": {
            "get": {
                "tags": ["vault"], "summary": "读取文件",
                "parameters": [{"name": "path", "in": "query", "required": True,
                                "schema": {"type": "string"}}],
                "responses": {"200": {"description": "文件内容"}}
            },
            "post": {
                "tags": ["vault"], "summary": "写入文件",
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "path":    {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                }}}},
                "responses": {"200": {"description": "写入结果"}}
            }
        },
        # ── Skills ─────────────────────────────────────
        "/skills": {
            "get": {"tags": ["skills"], "summary": "列出所有 Skill",
                    "parameters": [{"name": "category", "in": "query", "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Skill 列表"}}}
        },
        "/skills/{skill_id}": {
            "get": {"tags": ["skills"], "summary": "获取单个 Skill",
                    "parameters": [{"name": "skill_id", "in": "path", "required": True,
                                    "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Skill 详情"}}}
        },
        "/skills/{skill_id}/usage": {
            "post": {"tags": ["skills"], "summary": "记录 Skill 使用 & 评分",
                     "parameters": [{"name": "skill_id", "in": "path", "required": True,
                                     "schema": {"type": "string"}}],
                     "requestBody": {"content": {"application/json": {"schema": {
                         "type": "object",
                         "properties": {"score": {"type": "number", "minimum": 0, "maximum": 5}},
                     }}}},
                     "responses": {"200": {"description": "更新后的 Skill"}}}
        },
        # ── Reports ────────────────────────────────────
        "/reports/status": {
            "get": {"tags": ["reports"], "summary": "日报 / 周报可发送状态",
                    "responses": {"200": {"description": "状态"}}}
        },
        "/reports/daily": {
            "get": {"tags": ["reports"], "summary": "生成 / 获取日报",
                    "responses": {"200": {"description": "日报数据"}}}
        },
        "/reports/weekly": {
            "get": {"tags": ["reports"], "summary": "生成 / 获取周报",
                    "responses": {"200": {"description": "周报数据"}}}
        },
        # ── Shoucang ───────────────────────────────────
        "/shoucang/sop": {
            "post": {
                "tags": ["shoucang"], "summary": "触发守藏日常 SOP",
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "stream": {"type": "boolean", "description": "SSE 进度推送模式"},
                    }
                }}}},
                "responses": {
                    "200": {"description": "SSE stream 或后台触发确认"},
                }
            }
        },
        # ── Config ─────────────────────────────────────
        "/config/api-catalog": {
            "get": {"tags": ["config"], "summary": "获取所有 API 及配置状态",
                    "responses": {"200": {"description": "API catalog"}}}
        },
        "/config/api-save": {
            "post": {"tags": ["config"], "summary": "批量保存 API Keys",
                     "responses": {"200": {"description": "保存结果"}}}
        },
        "/config/api-test/{api_id}": {
            "post": {"tags": ["config"], "summary": "测试指定 API 连通性",
                     "parameters": [{"name": "api_id", "in": "path", "required": True,
                                     "schema": {"type": "string"}}],
                     "responses": {"200": {"description": "测试结果"}}}
        },

        # ── Membership ─────────────────────────────────
        "/membership/status": {
            "get": {
                "tags": ["membership"], "summary": "获取当前会员状态",
                "responses": {"200": {"description": "会员状态", "content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "tier":      {"type": "string", "enum": ["free", "pro"]},
                        "active":    {"type": "boolean"},
                        "expires":   {"type": "string", "nullable": True},
                        "days_left": {"type": "integer"},
                        "error":     {"type": "string"},
                    }
                }}}}}
            }
        },
        "/membership/activate": {
            "post": {
                "tags": ["membership"], "summary": "激活会员（输入激活码）",
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object", "required": ["code"],
                    "properties": {"code": {"type": "string", "example": "ANIMA-XXXX-XXXX-XXXX-XXXX-XXXXXXXX"}}
                }}}},
                "responses": {
                    "200": {"description": "激活成功"},
                    "400": {"description": "激活码无效或已过期"},
                }
            }
        },
        "/membership/deactivate": {
            "post": {
                "tags": ["membership"], "summary": "取消激活（退回免费版）",
                "responses": {"200": {"description": "已退回免费版"}}
            }
        },
    }
}


def get_spec() -> dict:
    """返回 OpenAPI 规格字典"""
    return SPEC


def get_spec_json() -> str:
    """返回 OpenAPI 规格 JSON 字符串"""
    return json.dumps(SPEC, ensure_ascii=False, indent=2)


SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Anima API Docs</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
SwaggerUIBundle({
  url: '/openapi.json',
  dom_id: '#swagger-ui',
  presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
  layout: 'BaseLayout',
  deepLinking: true,
});
</script>
</body>
</html>
"""
