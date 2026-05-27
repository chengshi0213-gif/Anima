"""
routes/config.py — Agent 配置、Onboarding/FTUE、TTS、API Catalog
"""
import asyncio
import json as _json
from pathlib import Path
from aiohttp import web

from .auth import CORS_HEADERS, _json_error
from onboarding import (
    is_ftue_done, mark_ftue_done, get_welcome_message, get_shoucang_first_run_prompt,
)


# ══════════════════════════════════════════════════════
#  Agent 配置（名称 / 音色 / 头像）
# ══════════════════════════════════════════════════════

DEFAULT_AGENT_NAMES = {
    "xi":       "Anima",
    "yiyi":     "晞",
    "tianyuan": "陶朱",
    "shoucang": "守藏",
    "executor": "执行者",
    "writer":   "写手",
    "reader":   "阅读者",
    "critic":   "评审",
}

# Agent 默认音色映射（edge-tts 声音）
AGENT_VOICES = {
    "xi":       "zh-CN-YunxiNeural",
    "yiyi":     "zh-CN-XiaoxiaoNeural",
    "tianyuan": "zh-CN-YunyangNeural",
    "shoucang": "zh-CN-YunjianNeural",
    "executor": "zh-CN-YunxiNeural",
    "writer":   "zh-CN-XiaoyiNeural",
    "reader":   "zh-CN-YunjianNeural",
    "critic":   "zh-CN-YunyangNeural",
}


def _agent_cfg_file():
    from config import DATA_DIR
    return DATA_DIR.parent / "agent_config.json"


def _load_agent_config() -> dict:
    f = _agent_cfg_file()
    if f.exists():
        return _json.loads(f.read_text("utf-8"))
    return {}


def _save_agent_config(data: dict):
    f = _agent_cfg_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


async def agent_config_get(request):
    """GET /config/agents — 返回 agent 名称 / 音色 / 描述"""
    cfg = _load_agent_config()
    names  = {**DEFAULT_AGENT_NAMES, **cfg.get("names", {})}
    voices = {**AGENT_VOICES,        **cfg.get("voices", {})}
    return web.json_response({"names": names, "voices": voices}, headers=CORS_HEADERS)


async def agent_config_set(request):
    """POST /config/agents — 保存 agent 名称 / 音色"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    cfg = _load_agent_config()
    if "names"  in body: cfg["names"]  = {**cfg.get("names",{}),  **body["names"]}
    if "voices" in body: cfg["voices"] = {**cfg.get("voices",{}), **body["voices"]}
    _save_agent_config(cfg)
    return web.json_response({"ok": True, "config": cfg}, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  TTS 接口（edge-tts）
# ══════════════════════════════════════════════════════

async def tts_handler(request):
    """POST /tts — 文字转语音"""
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text="invalid json")

    text  = body.get("text", "").strip()[:500]
    agent = body.get("agent", "xi")
    voice = body.get("voice") or AGENT_VOICES.get(agent, "zh-CN-YunxiNeural")

    if not text:
        return web.Response(status=400, text="text is empty")

    try:
        import edge_tts
        import io
        buf = io.BytesIO()
        communicate = edge_tts.Communicate(text, voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        buf.seek(0)
        audio_data = buf.read()
        if not audio_data:
            return web.Response(status=500, text="TTS 生成为空")
        return web.Response(
            body=audio_data,
            content_type="audio/mpeg",
            headers={**CORS_HEADERS, "Cache-Control": "no-store"},
        )
    except ImportError:
        return web.Response(status=501, text="edge-tts 未安装，请运行: pip install edge-tts")
    except Exception as e:
        return web.Response(status=500, text=f"TTS 错误: {e}")


async def tts_voices_handler(request):
    """GET /tts/voices — 返回 Agent 音色配置"""
    cfg = _load_agent_config()
    result = {}
    for agent_id, default_voice in AGENT_VOICES.items():
        result[agent_id] = cfg.get("voices", {}).get(agent_id, default_voice)
    return web.json_response({"voices": result}, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  Onboarding / 初始化配置接口
# ══════════════════════════════════════════════════════

async def setup_status_handler(request):
    """GET /setup/status — 是否已完成初始配置"""
    import config as _cfg_mod
    cfg = _load_agent_config()
    user_cfg = _cfg_mod._cfg.get("user", {}) if hasattr(_cfg_mod, "_cfg") else {}
    user_address = user_cfg.get("address", {})
    return web.json_response({
        "configured": _cfg_mod.is_configured(),
        "ftue_done":  is_ftue_done(),
        "agent_names": {**DEFAULT_AGENT_NAMES, **cfg.get("names", {})},
        "user_address": user_address,
        "keys": {
            "deepseek":  bool(_cfg_mod.DEEPSEEK_KEY and not _cfg_mod.DEEPSEEK_KEY.startswith("sk-xxx")),
            "kimi":      bool(_cfg_mod.KIMI_KEY      and not _cfg_mod.KIMI_KEY.startswith("sk-xxx")),
            "qwen":      bool(_cfg_mod.QWEN_KEY      and not _cfg_mod.QWEN_KEY.startswith("sk-xxx")),
            "openai":    bool(_cfg_mod.OPENAI_KEY    and not _cfg_mod.OPENAI_KEY.startswith("sk-xxx")),
        }
    }, headers=CORS_HEADERS)


async def setup_save_handler(request):
    """POST /setup/save — 保存初始配置（Onboarding 用）"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)

    import config as _cfg_mod

    # 保存 API keys
    api_updates = body.get("api", {})
    if api_updates:
        _cfg_mod.save_user_config({"api": api_updates})
        for attr, key in [
            ("DEEPSEEK_KEY","deepseek_key"),("KIMI_KEY","kimi_key"),
            ("QWEN_KEY","qwen_key"),("OPENAI_KEY","openai_key"),
            ("ANTHROPIC_KEY","anthropic_key"),("OPENROUTER_KEY","openrouter_key"),
        ]:
            v = api_updates.get(key)
            if v: setattr(_cfg_mod, attr, v)

    if "lang" in body:
        _cfg_mod.save_user_config({"lang": body["lang"]})

    if "agent_names" in body:
        cfg = _load_agent_config()
        cfg["names"] = {**cfg.get("names", {}), **body["agent_names"]}
        _save_agent_config(cfg)

    raw_address = body.get("user_address")
    if raw_address is not None:
        cleaned = {k: v for k, v in raw_address.items() if v and v.strip()}
        _cfg_mod.save_user_config({"user": {"address": cleaned}})
        _cfg_mod.reload_user_config()

    if not is_ftue_done():
        mark_ftue_done(body.get("agent_names", {}))

    return web.json_response({"ok": True}, headers=CORS_HEADERS)


async def setup_welcome_handler(request):
    """GET /setup/welcome — 返回 FTUE 欢迎消息"""
    cfg = _load_agent_config()
    names = {**DEFAULT_AGENT_NAMES, **cfg.get("names", {})}
    done = is_ftue_done()
    return web.json_response({
        "is_first_run": not done,
        "welcome_message": get_welcome_message(names) if not done else None,
    }, headers=CORS_HEADERS)


async def setup_complete_handler(request):
    """POST /setup/complete — 标记 FTUE 完成，触发守藏初始化 SOP"""
    servers = request.app["servers"]
    cfg = _load_agent_config()
    names = {**DEFAULT_AGENT_NAMES, **cfg.get("names", {})}

    already_done = is_ftue_done()
    if not already_done:
        mark_ftue_done(names)
        shoucang = servers.get("shoucang")
        if shoucang:
            init_prompt = get_shoucang_first_run_prompt()
            asyncio.create_task(shoucang.worker.run(init_prompt))

    return web.json_response({
        "ok": True,
        "welcome_message": get_welcome_message(names),
        "first_run": not already_done,
    }, headers=CORS_HEADERS)


# ══════════════════════════════════════════════════════
#  API Catalog（丰富化配置）
# ══════════════════════════════════════════════════════

API_CATALOG = [
    # LLM
    {"id":"deepseek",  "name":"DeepSeek",     "category":"llm",    "icon":"🔵",
     "desc":"Anima + 陶朱主脑，国内最强编程推理模型",
     "signup_url":"https://platform.deepseek.com",  "config_key":"deepseek_key",  "required":True},
    {"id":"kimi",      "name":"Kimi",          "category":"llm",    "icon":"🌙",
     "desc":"陶朱团队写手/阅读者，超长上下文（128K）",
     "signup_url":"https://platform.moonshot.cn",   "config_key":"kimi_key",      "required":True},
    {"id":"qwen",      "name":"通义千问",       "category":"llm",    "icon":"🟢",
     "desc":"知识库 Embedding + 守藏检索增强",
     "signup_url":"https://dashscope.aliyun.com",   "config_key":"qwen_key",      "required":False},
    {"id":"openai",    "name":"OpenAI",         "category":"llm",    "icon":"⚫",
     "desc":"GPT 系列模型（可选）",
     "signup_url":"https://platform.openai.com",    "config_key":"openai_key",    "required":False},
    {"id":"anthropic", "name":"Anthropic",      "category":"llm",    "icon":"🟤",
     "desc":"Claude 系列模型（可选）",
     "signup_url":"https://console.anthropic.com",  "config_key":"anthropic_key", "required":False},
    {"id":"openrouter","name":"OpenRouter",     "category":"llm",    "icon":"🔀",
     "desc":"统一路由（Claude/GPT 中转），多模型备用",
     "signup_url":"https://openrouter.ai",          "config_key":"openrouter_key","required":False},
    # 搜索 & 网络
    {"id":"tavily",    "name":"Tavily Search",  "category":"search", "icon":"🔍",
     "desc":"AI 原生搜索引擎，联网搜索最推荐，免费 1000次/月",
     "signup_url":"https://tavily.com",             "config_key":"tavily_key",    "required":False},
    {"id":"serper",    "name":"Serper (Google)","category":"search", "icon":"🌐",
     "desc":"Google 搜索 API，结果最全面",
     "signup_url":"https://serper.dev",             "config_key":"serper_key",    "required":False},
    {"id":"jina",      "name":"Jina AI Reader", "category":"search", "icon":"📄",
     "desc":"网页内容读取与解析，抓取任意网页正文",
     "signup_url":"https://jina.ai",                "config_key":"jina_key",      "required":False},
    {"id":"firecrawl", "name":"Firecrawl",      "category":"search", "icon":"🕷️",
     "desc":"深度网站爬取，支持整站抓取与结构化提取",
     "signup_url":"https://firecrawl.dev",          "config_key":"firecrawl_key", "required":False},
    # 效率工具
    {"id":"github",    "name":"GitHub",         "category":"tools",  "icon":"🐙",
     "desc":"项目图谱分析、代码搜索、Issue 管理",
     "signup_url":"https://github.com/settings/tokens","config_key":"github_token","required":False},
    {"id":"smtp",      "name":"邮件 SMTP",       "category":"tools",  "icon":"📧",
     "desc":"发送邮件通知（工作流输出节点）",
     "signup_url":"",                               "config_key":"smtp_host",     "required":False},
    # 存储
    {"id":"notion",    "name":"Notion",          "category":"storage","icon":"📝",
     "desc":"同步笔记到 Notion 数据库（可选，Obsidian 优先）",
     "signup_url":"https://www.notion.so/my-integrations","config_key":"notion_key","required":False},
]


def _get_api_statuses() -> list:
    """返回所有 API 的配置状态"""
    import config as _cfg
    key_map = {
        "deepseek_key":  _cfg.DEEPSEEK_KEY,
        "kimi_key":      _cfg.KIMI_KEY,
        "qwen_key":      _cfg.QWEN_KEY,
        "openai_key":    _cfg.OPENAI_KEY,
        "anthropic_key": _cfg.ANTHROPIC_KEY,
        "openrouter_key":_cfg.OPENROUTER_KEY,
        "tavily_key":    _cfg.TAVILY_KEY,
        "serper_key":    _cfg.SERPER_KEY,
        "jina_key":      _cfg.JINA_KEY,
        "firecrawl_key": _cfg.FIRECRAWL_KEY,
        "github_token":  _cfg.GITHUB_TOKEN,
    }
    result = []
    for api in API_CATALOG:
        ck  = api["config_key"]
        val = key_map.get(ck, "")
        configured = bool(val and not val.startswith("sk-xxx") and len(val) > 4)
        result.append({**api, "configured": configured,
                        "masked_key": f"{val[:6]}…{val[-4:]}" if configured else ""})
    return result


async def api_catalog_handler(request):
    """GET /config/api-catalog — 所有 API 及配置状态"""
    statuses = await asyncio.to_thread(_get_api_statuses)
    return web.json_response({"apis": statuses}, headers=CORS_HEADERS)


async def api_save_handler(request):
    """POST /config/api-save — 保存 API keys"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    import config as _cfg
    allowed = {
        "deepseek_key", "kimi_key", "qwen_key", "openai_key",
        "anthropic_key", "openrouter_key", "glm_key", "gemini_key",
        "tavily_key", "serper_key", "jina_key", "firecrawl_key", "github_token",
        "smtp_host", "smtp_port", "smtp_user", "smtp_pass",
        "notion_key",
    }
    updates = {k: v for k, v in body.items() if k in allowed and v and not v.startswith("•")}
    if updates:
        _cfg.save_user_config({"api": updates})
        _cfg.reload_user_config()
    return web.json_response({"ok": True}, headers=CORS_HEADERS)


async def api_test_handler(request):
    """POST /config/api-test/{api_id} — 测试 API 是否可用"""
    api_id = request.match_info["api_id"]
    test_urls = {
        "deepseek":  "https://api.deepseek.com/models",
        "kimi":      "https://api.moonshot.cn/v1/models",
        "qwen":      "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
        "openai":    "https://api.openai.com/v1/models",
        "tavily":    "https://api.tavily.com/search",
    }
    url = test_urls.get(api_id)
    if not url:
        return web.json_response({"ok": False, "error": "无法测试此 API"}, headers=CORS_HEADERS)
    import config as _cfg
    key_map = {"deepseek":_cfg.DEEPSEEK_KEY,"kimi":_cfg.KIMI_KEY,
               "qwen":_cfg.QWEN_KEY,"openai":_cfg.OPENAI_KEY}
    key = key_map.get(api_id,"")
    if not key:
        return web.json_response({"ok": False, "error": "API Key 未配置"}, headers=CORS_HEADERS)
    try:
        import aiohttp as _aiohttp
        async with _aiohttp.ClientSession() as sess:
            async with sess.get(url, headers={"Authorization": f"Bearer {key}"},
                                timeout=_aiohttp.ClientTimeout(total=5)) as r:
                ok = r.status in (200, 404, 422)
        return web.json_response({"ok": ok}, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, headers=CORS_HEADERS)


def register(app):
    # Agent 配置
    app.router.add_get("/config/agents",           agent_config_get)
    app.router.add_post("/config/agents",          agent_config_set)
    # TTS
    app.router.add_post("/tts",                    tts_handler)
    app.router.add_get("/tts/voices",              tts_voices_handler)
    # Onboarding / FTUE
    app.router.add_get("/setup/status",            setup_status_handler)
    app.router.add_post("/setup/save",             setup_save_handler)
    app.router.add_get("/setup/welcome",           setup_welcome_handler)
    app.router.add_post("/setup/complete",         setup_complete_handler)
    # API Catalog
    app.router.add_get("/config/api-catalog",      api_catalog_handler)
    app.router.add_post("/config/api-save",        api_save_handler)
    app.router.add_post("/config/api-test/{api_id}", api_test_handler)
