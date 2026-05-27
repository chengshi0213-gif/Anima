#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anima — 集中配置
所有路径、端口、API Key 从这里读取
优先级: 环境变量 > config/config.yaml > 默认值
"""
import os
import sys
import shutil
import yaml
from pathlib import Path

# ── 项目根目录（兼容 PyInstaller 打包后的路径）──
if getattr(sys, 'frozen', False):
    BACKEND_DIR = Path(sys.executable).parent
else:
    BACKEND_DIR = Path(__file__).parent

PROJECT_DIR = BACKEND_DIR.parent

# ── 数据目录：~/.anima/data/
#    兼容迁移：若 ~/.anima 不存在但旧版 ~/.hermes 存在，自动迁移
# ──────────────────────────────────────────────────────────────────
_anima_home  = Path.home() / ".anima"
_legacy_home = Path.home() / ".hermes"

def _migrate_legacy():
    """一次性把 ~/.hermes 迁移到 ~/.anima（静默执行）"""
    if _anima_home.exists() or not _legacy_home.exists():
        return
    try:
        shutil.copytree(str(_legacy_home), str(_anima_home))
    except Exception:
        _anima_home.mkdir(parents=True, exist_ok=True)

_migrate_legacy()

_default_data = _anima_home / "data"
DATA_DIR = Path(os.environ.get("ANIMA_DATA_DIR", str(_default_data)))
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR       = DATA_DIR / "logs"
SESSIONS_DB   = DATA_DIR / "sessions.db"
WORKFLOWS_DIR = DATA_DIR / "workflows"

LOG_DIR.mkdir(parents=True, exist_ok=True)
WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)

# ── Agent workspace ──
WORKSPACE_DIR = Path(os.environ.get(
    "ANIMA_WORKSPACE",
    str(_anima_home / "workspace")
))
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# ── 读取 YAML 配置 ──
# 优先从 ~/.anima/config.yaml 读取，其次打包内置
_user_cfg_path    = _anima_home / "config.yaml"
_bundled_cfg_path = BACKEND_DIR / "config" / "config.yaml"
_cfg_example      = BACKEND_DIR / "config" / "config.example.yaml"
_cfg: dict = {}

if _user_cfg_path.exists():
    with open(_user_cfg_path, "r", encoding="utf-8") as f:
        _cfg = yaml.safe_load(f) or {}
elif _bundled_cfg_path.exists():
    with open(_bundled_cfg_path, "r", encoding="utf-8") as f:
        _cfg = yaml.safe_load(f) or {}
elif _cfg_example.exists():
    _user_cfg_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_cfg_example, _user_cfg_path)


def _get(key: str, default=None):
    """从环境变量或 YAML 配置读值"""
    env_key = f"ANIMA_{key.upper().replace('.', '_')}"
    if env_key in os.environ:
        return os.environ[env_key]
    parts = key.split(".")
    val = _cfg
    for p in parts:
        if not isinstance(val, dict):
            return default
        val = val.get(p, default)
    return val if val is not None else default


def save_user_config(updates: dict):
    """将更新写入 ~/.anima/config.yaml"""
    import yaml as _yaml
    cfg = {}
    if _user_cfg_path.exists():
        with open(_user_cfg_path, "r", encoding="utf-8") as f:
            cfg = _yaml.safe_load(f) or {}
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    _user_cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(_user_cfg_path, "w", encoding="utf-8") as f:
        _yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
    global _cfg
    _cfg = cfg


def is_configured() -> bool:
    """判断是否已完成初始配置（至少有一个 API Key）"""
    keys = [DEEPSEEK_KEY, KIMI_KEY, QWEN_KEY, OPENAI_KEY, ANTHROPIC_KEY]
    return any(k and not k.startswith("sk-xxx") for k in keys)


# ── 端口 ──
PORT_WS        = int(_get("port.ws",       9100))
PORT_XI        = int(_get("port.xi",       9101))   # Anima（主助理）
PORT_YIYI      = int(_get("port.yiyi",     9102))
PORT_TIANYUAN  = int(_get("port.tianyuan", 9103))
PORT_DASHBOARD = int(_get("port.dashboard", 9119))

# ── API Keys — LLM ──
DEEPSEEK_KEY   = _get("api.deepseek_key",   os.environ.get("DEEPSEEK_API_KEY",   ""))
ANTHROPIC_KEY  = _get("api.anthropic_key",  os.environ.get("ANTHROPIC_API_KEY",  ""))
OPENAI_KEY     = _get("api.openai_key",     os.environ.get("OPENAI_API_KEY",     ""))
QWEN_KEY       = _get("api.qwen_key",       os.environ.get("QWEN_API_KEY",       ""))
KIMI_KEY       = _get("api.kimi_key",       os.environ.get("KIMI_API_KEY",       ""))
GLM_KEY        = _get("api.glm_key",        os.environ.get("GLM_API_KEY",        ""))
GEMINI_KEY     = _get("api.gemini_key",     os.environ.get("GEMINI_API_KEY",     ""))
OPENROUTER_KEY = _get("api.openrouter_key", os.environ.get("OPENROUTER_API_KEY", ""))

# ── API Keys — 搜索 & 工具 ──
TAVILY_KEY     = _get("api.tavily_key",     os.environ.get("TAVILY_API_KEY",     ""))
SERPER_KEY     = _get("api.serper_key",     os.environ.get("SERPER_API_KEY",     ""))
JINA_KEY       = _get("api.jina_key",       os.environ.get("JINA_API_KEY",       ""))
FIRECRAWL_KEY  = _get("api.firecrawl_key",  os.environ.get("FIRECRAWL_API_KEY",  ""))
GITHUB_TOKEN   = _get("api.github_token",   os.environ.get("GITHUB_TOKEN",       ""))

# ── 身份文件 ──
IDENTITY_DIR = Path(_get("identity_dir", str(_anima_home / "identity")))
IDENTITY_DIR.mkdir(parents=True, exist_ok=True)

# ── 记忆存储后端 ──
MEMORY_BACKEND = _get("memory.backend",        "sqlite")
OBSIDIAN_VAULT = _get("memory.obsidian_vault", "")

# ── 安全 ──
WEBHOOK_TOKEN = _get("security.webhook_token", os.environ.get("ANIMA_WEBHOOK_TOKEN", ""))

# ── 用户称呼系统 ──
# 每个 Agent 可以用不同的方式称呼用户
# Onboarding 时收集，存入 config.yaml 的 user 节
USER_NAME = _get("user.name", "")   # 用户真实姓名/昵称（onboarding 收集）

def get_user_address(agent_id: str) -> str:
    """返回指定 Agent 对用户的称呼。未配置时退化到 USER_NAME，再退化到『你』。"""
    addr = _get(f"user.address.{agent_id}", "")
    if addr:
        return addr
    if USER_NAME:
        return USER_NAME
    return "你"

def reload_user_config():
    """Onboarding/设置写入后调用，刷新内存中的用户称呼和 API Keys。"""
    global USER_NAME, _cfg
    global DEEPSEEK_KEY, ANTHROPIC_KEY, OPENAI_KEY, QWEN_KEY, KIMI_KEY
    global GLM_KEY, GEMINI_KEY, OPENROUTER_KEY
    global TAVILY_KEY, SERPER_KEY, JINA_KEY, FIRECRAWL_KEY, GITHUB_TOKEN
    if _user_cfg_path.exists():
        import yaml as _yaml
        with open(_user_cfg_path, "r", encoding="utf-8") as f:
            _cfg = _yaml.safe_load(f) or {}
    USER_NAME      = _get("user.name", "")
    DEEPSEEK_KEY   = _get("api.deepseek_key",   os.environ.get("DEEPSEEK_API_KEY",   ""))
    ANTHROPIC_KEY  = _get("api.anthropic_key",  os.environ.get("ANTHROPIC_API_KEY",  ""))
    OPENAI_KEY     = _get("api.openai_key",     os.environ.get("OPENAI_API_KEY",     ""))
    QWEN_KEY       = _get("api.qwen_key",       os.environ.get("QWEN_API_KEY",       ""))
    KIMI_KEY       = _get("api.kimi_key",       os.environ.get("KIMI_API_KEY",       ""))
    GLM_KEY        = _get("api.glm_key",        os.environ.get("GLM_API_KEY",        ""))
    GEMINI_KEY     = _get("api.gemini_key",     os.environ.get("GEMINI_API_KEY",     ""))
    OPENROUTER_KEY = _get("api.openrouter_key", os.environ.get("OPENROUTER_API_KEY", ""))
    TAVILY_KEY     = _get("api.tavily_key",     os.environ.get("TAVILY_API_KEY",     ""))
    SERPER_KEY     = _get("api.serper_key",     os.environ.get("SERPER_API_KEY",     ""))
    JINA_KEY       = _get("api.jina_key",       os.environ.get("JINA_API_KEY",       ""))
    FIRECRAWL_KEY  = _get("api.firecrawl_key",  os.environ.get("FIRECRAWL_API_KEY",  ""))
    GITHUB_TOKEN   = _get("api.github_token",   os.environ.get("GITHUB_TOKEN",       ""))
