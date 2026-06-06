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
    "executor": "执行者",
    "writer":   "写手",
    "reader":   "阅读者",
    "critic":   "评审",
}

# Agent 默认音色映射（edge-tts 声音）
AGENT_VOICES = {
    "xi":       "zh-CN-XiaoxiaoNeural",
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


async def personas_handler(request):
    """GET /config/personas — 返回四个核心人格的人格卡（前端展示用，不含完整 prompt）。

    名称若被用户在 /config/agents 改过，则用改后的名字覆盖人格卡默认显示名。
    """
    from persona import list_personas
    cfg   = _load_agent_config()
    names = {**DEFAULT_AGENT_NAMES, **cfg.get("names", {})}
    cards = list_personas()
    for c in cards:
        if c["id"] in names:
            c["name"] = names[c["id"]]
    return web.json_response({"personas": cards}, headers=CORS_HEADERS)


async def search_usage_handler(request):
    """GET /search/usage — 当月联网检索用量 + Tavily 剩余额度"""
    from websearch import get_usage
    usage = await asyncio.to_thread(get_usage)
    return web.json_response(usage, headers=CORS_HEADERS)


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
            ("GLM_KEY","glm_key"),("MIMO_KEY","mimo_key"),
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
     "desc":"超长上下文（128K），写作/长文阅读（可选）",
     "signup_url":"https://platform.moonshot.cn",   "config_key":"kimi_key",      "required":False},
    {"id":"qwen",      "name":"通义千问",       "category":"llm",    "icon":"🟢",
     "desc":"知识库 Embedding + 守藏检索增强（可选）",
     "signup_url":"https://dashscope.aliyun.com",   "config_key":"qwen_key",      "required":False},
    {"id":"glm",       "name":"智谱 GLM",       "category":"llm",    "icon":"🟣",
     "desc":"GLM-4.6 旗舰，GLM-4-Flash 免费可用（可选）",
     "signup_url":"https://open.bigmodel.cn",       "config_key":"glm_key",       "required":False},
    {"id":"mimo",      "name":"小米 MiMo",      "category":"llm",    "icon":"🟠",
     "desc":"小米 MiMo 推理模型，OpenAI 兼容（可选）",
     "signup_url":"https://xiaomimimo.com",         "config_key":"mimo_key",      "required":False},
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
        "glm_key":       _cfg.GLM_KEY,
        "mimo_key":      _cfg.MIMO_KEY,
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
        "anthropic_key", "openrouter_key", "glm_key", "mimo_key", "gemini_key",
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
    import config as _cfg
    test_urls = {
        "deepseek":  "https://api.deepseek.com/models",
        "kimi":      "https://api.moonshot.cn/v1/models",
        "qwen":      "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
        "openai":    "https://api.openai.com/v1/models",
        "glm":       _cfg.GLM_URL.rstrip("/") + "/models",
        "mimo":      _cfg.MIMO_URL.rstrip("/") + "/models",
        "tavily":    "https://api.tavily.com/search",
    }
    url = test_urls.get(api_id)
    if not url:
        return web.json_response({"ok": False, "error": "无法测试此 API"}, headers=CORS_HEADERS)
    key_map = {"deepseek":_cfg.DEEPSEEK_KEY,"kimi":_cfg.KIMI_KEY,
               "qwen":_cfg.QWEN_KEY,"openai":_cfg.OPENAI_KEY,
               "glm":_cfg.GLM_KEY,"mimo":_cfg.MIMO_KEY}
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


async def data_home_get(request):
    """GET /config/data-home — 当前数据主目录信息"""
    import config as _cfg
    return web.json_response(_cfg.get_data_home(), headers=CORS_HEADERS)


async def data_home_set(request):
    """POST /config/data-home — 设置（可迁移）数据主目录。需重启生效。
    body: {path, migrate?:bool}"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    import config as _cfg
    import shutil
    from pathlib import Path
    ok, resolved = _cfg.validate_data_home(body.get("path", ""))
    if not ok:
        return web.json_response({"ok": False, "error": resolved}, status=400, headers=CORS_HEADERS)
    migrate = bool(body.get("migrate", True))
    moved = []
    if migrate:
        try:
            cur = Path(_cfg.get_data_home()["anima_home"])
            for sub in _cfg.DATA_HOME_SUBDIRS:
                src = cur / sub
                if src.exists():
                    await asyncio.to_thread(
                        shutil.copytree, str(src), str(Path(resolved) / sub), dirs_exist_ok=True
                    )
                    moved.append(sub)
        except Exception as e:
            return web.json_response({"ok": False, "error": f"迁移失败：{e}"},
                                     status=500, headers=CORS_HEADERS)
    _cfg.save_user_config({"anima_home": resolved})
    return web.json_response({
        "ok": True, "path": resolved, "moved": moved,
        "restart_required": True,
        "message": "已保存。重启 Anima 后，数据将从新目录读取。",
    }, headers=CORS_HEADERS)


async def data_home_reset(request):
    """POST /config/data-home/reset — 恢复默认目录（不删数据，仅改指向）。需重启。"""
    import config as _cfg
    _cfg.save_user_config({"anima_home": ""})
    return web.json_response({"ok": True, "restart_required": True,
                             "message": "已恢复默认目录，重启后生效。"}, headers=CORS_HEADERS)


# ── 诊断 / 崩溃上报 ───────────────────────────────────────────
async def diagnostics_status(request):
    """GET /diagnostics/status — 返回崩溃文件列表，供设置页展示。"""
    try:
        import crash_reporter
        crashes = await asyncio.to_thread(crash_reporter.list_crashes)
        return web.json_response({"crashes": crashes}, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"crashes": [], "error": str(e)},
                                 headers=CORS_HEADERS)


async def diagnostics_export(request):
    """POST /diagnostics/export — 打包诊断 zip（脱敏），返回本地路径。
    请求体可选 {frontend_errors: [...]}（前端错误队列）。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    fe_errors = body.get("frontend_errors") if isinstance(body, dict) else None
    try:
        import crash_reporter
        result = await asyncio.to_thread(
            crash_reporter.export_diagnostics, fe_errors, "")
        status = 200 if result.get("ok") else 500
        return web.json_response(result, status=status, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)},
                                 status=500, headers=CORS_HEADERS)


def register(app):
    # Agent 配置
    app.router.add_get("/config/agents",           agent_config_get)
    app.router.add_post("/config/agents",          agent_config_set)
    app.router.add_get("/config/personas",         personas_handler)
    # 联网检索用量
    app.router.add_get("/search/usage",            search_usage_handler)
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
    # 数据目录自定义
    app.router.add_get("/config/data-home",        data_home_get)
    app.router.add_post("/config/data-home",       data_home_set)
    app.router.add_post("/config/data-home/reset", data_home_reset)
    # 诊断 / 崩溃上报
    app.router.add_get("/diagnostics/status",      diagnostics_status)
    app.router.add_post("/diagnostics/export",     diagnostics_export)
