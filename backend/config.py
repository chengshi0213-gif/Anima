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

# ── 版本单一真源（R2）──
# 后端唯一版本常量；横幅/接口统一引用，杜绝硬编码。
# 发版时与 package.json / tauri.conf.json / Cargo.toml 三清单保持一致。
ANIMA_VERSION = "1.3.0"

# ── 项目根目录（兼容 PyInstaller 打包后的路径）──
if getattr(sys, 'frozen', False):
    BACKEND_DIR = Path(sys.executable).parent
else:
    BACKEND_DIR = Path(__file__).parent

PROJECT_DIR = BACKEND_DIR.parent

# ── 引导目录：~/.anima/（固定，永远存 config.yaml，不随数据迁移）──
#    兼容迁移：若 ~/.anima 不存在但旧版 ~/.hermes 存在，自动迁移
# ──────────────────────────────────────────────────────────────────
_BOOT_HOME   = Path.home() / ".anima"
_legacy_home = Path.home() / ".hermes"

def _migrate_legacy():
    """一次性把 ~/.hermes 迁移到 ~/.anima（静默执行）"""
    if _BOOT_HOME.exists() or not _legacy_home.exists():
        return
    try:
        shutil.copytree(str(_legacy_home), str(_BOOT_HOME))
    except Exception:
        _BOOT_HOME.mkdir(parents=True, exist_ok=True)

_migrate_legacy()
_BOOT_HOME.mkdir(parents=True, exist_ok=True)

# ── 读取 YAML 配置（config.yaml 始终在引导目录，不随数据目录迁移）──
_user_cfg_path    = _BOOT_HOME / "config.yaml"
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

# ── 数据主目录：可自定义（别都堆在 C 盘）──
#    优先级：环境变量 ANIMA_HOME > config.yaml 的 anima_home > 默认 ~/.anima
#    数据 / 技能 / 工作区 / 身份 全部挂在此目录下；config.yaml 始终留在引导目录。
_custom_home = os.environ.get("ANIMA_HOME") or (_cfg.get("anima_home") if isinstance(_cfg, dict) else "") or ""
_custom_home = str(_custom_home).strip()
try:
    _anima_home = Path(_custom_home) if _custom_home else _BOOT_HOME
    _anima_home.mkdir(parents=True, exist_ok=True)
except Exception:
    _anima_home = _BOOT_HOME
    _anima_home.mkdir(parents=True, exist_ok=True)

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


def _get(key: str, default=None):
    """从环境变量或 YAML 配置读值（敏感字段透明解密）"""
    env_key = f"ANIMA_{key.upper().replace('.', '_')}"
    if env_key in os.environ:
        return os.environ[env_key]
    parts = key.split(".")
    val = _cfg
    for p in parts:
        if not isinstance(val, dict):
            return default
        val = val.get(p, default)
    if val is None:
        return default
    # 透明解密：仅对带 marker 的密文生效，旧明文原样返回
    try:
        import secret_box
        if secret_box.is_encrypted(val):
            return secret_box.decrypt(val)
    except Exception:
        pass
    return val


def save_user_config(updates: dict):
    """将更新写入 ~/.anima/config.yaml（敏感字段透明加密）"""
    import yaml as _yaml
    # 写盘前加密敏感叶子字段（API Key / Token 等）
    try:
        import secret_box
        updates = secret_box.encrypt_sensitive_tree(updates)
    except Exception:
        pass
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


def migrate_encrypt_secrets():
    """
    一次性迁移：把 config.yaml 中残留的明文敏感字段加密。
    幂等——无明文需要加密时直接返回（升级后首次运行才会真正写盘）。
    由服务入口显式调用，避免在 import / 测试时意外写盘。
    """
    try:
        import secret_box
        import yaml as _yaml
    except Exception:
        return
    if not _user_cfg_path.exists():
        return
    try:
        with open(_user_cfg_path, "r", encoding="utf-8") as f:
            cfg = _yaml.safe_load(f) or {}
    except Exception:
        return

    found_plain = [False]

    def _scan(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, (dict, list)):
                    _scan(v)
                elif (secret_box.looks_sensitive(k) and isinstance(v, str)
                      and v and not secret_box.is_encrypted(v)):
                    found_plain[0] = True

    _scan(cfg)
    if not found_plain[0]:
        return

    encrypted = secret_box.encrypt_sensitive_tree(cfg)
    try:
        with open(_user_cfg_path, "w", encoding="utf-8") as f:
            _yaml.dump(encrypted, f, allow_unicode=True, default_flow_style=False)
        global _cfg
        _cfg = encrypted
        import logging
        logging.getLogger("anima.secret").info(
            "已将 config.yaml 中的明文 API Key 迁移为加密存储")
    except Exception as e:
        import logging
        logging.getLogger("anima.secret").error("加密迁移写盘失败: %s", e)


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
MIMO_KEY       = _get("api.mimo_key",        os.environ.get("MIMO_API_KEY",       ""))
GEMINI_KEY     = _get("api.gemini_key",     os.environ.get("GEMINI_API_KEY",     ""))
OPENROUTER_KEY = _get("api.openrouter_key", os.environ.get("OPENROUTER_API_KEY", ""))
# 可自定义 base_url（MiMo 暂无统一官方端点，默认走小米开放平台兼容地址，用户可在 config.yaml 覆盖）
GLM_URL        = _get("api.glm_url",         "https://open.bigmodel.cn/api/paas/v4")
MIMO_URL       = _get("api.mimo_url",        "https://api.xiaomimimo.com/v1")

# ── API Keys — 搜索 & 工具 ──
TAVILY_KEY     = _get("api.tavily_key",     os.environ.get("TAVILY_API_KEY",     ""))
SERPER_KEY     = _get("api.serper_key",     os.environ.get("SERPER_API_KEY",     ""))
JINA_KEY       = _get("api.jina_key",       os.environ.get("JINA_API_KEY",       ""))
FIRECRAWL_KEY  = _get("api.firecrawl_key",  os.environ.get("FIRECRAWL_API_KEY",  ""))
GITHUB_TOKEN   = _get("api.github_token",   os.environ.get("GITHUB_TOKEN",       ""))

# ── Supabase（邀请码系统）──
SUPABASE_URL     = _get("supabase.url",      os.environ.get("SUPABASE_URL",      ""))
SUPABASE_ANON_KEY = _get("supabase.anon_key", os.environ.get("SUPABASE_ANON_KEY", ""))

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
    global GLM_KEY, MIMO_KEY, GEMINI_KEY, OPENROUTER_KEY
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
    MIMO_KEY       = _get("api.mimo_key",        os.environ.get("MIMO_API_KEY",       ""))
    GEMINI_KEY     = _get("api.gemini_key",     os.environ.get("GEMINI_API_KEY",     ""))
    OPENROUTER_KEY = _get("api.openrouter_key", os.environ.get("OPENROUTER_API_KEY", ""))
    TAVILY_KEY     = _get("api.tavily_key",     os.environ.get("TAVILY_API_KEY",     ""))
    SERPER_KEY     = _get("api.serper_key",     os.environ.get("SERPER_API_KEY",     ""))
    JINA_KEY       = _get("api.jina_key",       os.environ.get("JINA_API_KEY",       ""))
    FIRECRAWL_KEY  = _get("api.firecrawl_key",  os.environ.get("FIRECRAWL_API_KEY",  ""))
    GITHUB_TOKEN   = _get("api.github_token",   os.environ.get("GITHUB_TOKEN",       ""))
    # 关键：agent_base 在 import 时拷贝了这些 key（值拷贝），reload 后必须同步推过去，
    # 否则用户配完 key 不重启不生效（单 key 用全功能也依赖此）。
    try:
        import sys as _sys
        _ab = _sys.modules.get("agent_base")
        if _ab is not None:
            for _k in ("DEEPSEEK_KEY", "ANTHROPIC_KEY", "OPENAI_KEY", "QWEN_KEY", "KIMI_KEY",
                       "GLM_KEY", "MIMO_KEY", "GEMINI_KEY", "OPENROUTER_KEY"):
                if hasattr(_ab, _k):
                    setattr(_ab, _k, globals()[_k])
    except Exception:
        pass


# ── 数据目录自定义 ─────────────────────────────────────────────────
# 子目录清单（迁移时随数据主目录一起搬，config.yaml 不在其中）
DATA_HOME_SUBDIRS = ["data", "skills", "workspace", "identity"]


def get_data_home() -> dict:
    """返回当前数据主目录信息，供设置页展示。"""
    return {
        "anima_home":   str(_anima_home),
        "data_dir":     str(DATA_DIR),
        "default_home": str(_BOOT_HOME),
        "is_default":   str(_anima_home) == str(_BOOT_HOME),
        "subdirs":      DATA_HOME_SUBDIRS,
    }


def validate_data_home(new_path: str) -> tuple[bool, str]:
    """校验新数据目录是否可用。返回 (ok, 规范化路径或错误信息)。"""
    p = (new_path or "").strip().strip('"')
    if not p:
        return False, "路径为空"
    try:
        target = Path(p).expanduser()
        if not target.is_absolute():
            return False, "请使用绝对路径（如 D:\\AnimaData）"
        cur = _anima_home.resolve()
        try:
            tr = target.resolve()
        except Exception:
            tr = target
        if str(tr) == str(cur):
            return False, "与当前目录相同"
        # 防止与当前目录互相嵌套（会导致递归复制）
        if str(tr).startswith(str(cur) + os.sep) or str(cur).startswith(str(tr) + os.sep):
            return False, "新目录不能与当前目录互相嵌套"
        target.mkdir(parents=True, exist_ok=True)
        # 可写性探测
        probe = target / ".anima_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, str(target)
    except PermissionError:
        return False, "该目录没有写入权限"
    except Exception as e:
        return False, f"路径无效：{e}"
