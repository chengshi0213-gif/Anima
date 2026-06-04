#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_injector.py — 记忆注入门面（Backend 工厂）

Agent 代码、websocket_server.py 只调用这里的函数，
不需要知道底层用的是 SQLite 还是 Obsidian。

后端选择逻辑（优先级从高到低）：
  1. config.MEMORY_BACKEND（~/.anima/config.yaml 中的 memory.backend）
  2. 默认：sqlite
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from memory_backend import MemoryBackend, MemoryEntry

# ── 单例 & 注入缓存 ──────────────────────────────────────────────
_backend: Optional[MemoryBackend] = None
_INJECT_CACHE: dict[str, tuple[float, str]] = {}   # agent_id → (ts, text)
_CACHE_TTL = 300   # 5 分钟


# ── 后端工厂 ─────────────────────────────────────────────────────

def _load_backend() -> MemoryBackend:
    """根据 config 实例化对应后端"""
    try:
        import config as _cfg
        backend_type  = getattr(_cfg, "MEMORY_BACKEND",  "sqlite")
        obsidian_path = getattr(_cfg, "OBSIDIAN_VAULT",  "")
    except Exception:
        backend_type, obsidian_path = "sqlite", ""

    if backend_type == "obsidian" and obsidian_path:
        vault = Path(obsidian_path).expanduser()
        from memory_obsidian import ObsidianMemoryBackend
        return ObsidianMemoryBackend(vault)
    else:
        from memory_sqlite import SQLiteMemoryBackend
        return SQLiteMemoryBackend()


def get_backend(reload: bool = False) -> MemoryBackend:
    """返回当前激活的记忆后端（单例，可强制重载）"""
    global _backend
    if _backend is None or reload:
        _backend = _load_backend()
    return _backend


def invalidate_cache(agent_id: Optional[str] = None):
    """写入记忆或切换后端后调用，让下次注入读取最新数据"""
    if agent_id:
        _INJECT_CACHE.pop(agent_id, None)
    else:
        _INJECT_CACHE.clear()


# ── 后端切换 & 迁移 ──────────────────────────────────────────────

def switch_backend(backend_type: str,
                   obsidian_path: str = "",
                   migrate: bool = False) -> dict:
    """
    切换后端并持久化到 config.yaml。
    migrate=True 时自动将当前后端数据迁移到新后端。
    """
    global _backend

    if backend_type not in ("sqlite", "obsidian"):
        return {"ok": False, "error": f"未知后端类型：{backend_type}"}

    if backend_type == "obsidian" and not obsidian_path:
        return {"ok": False, "error": "切换到 Obsidian 需要提供 Vault 路径"}

    migrated = 0
    if migrate and _backend is not None:
        try:
            result = migrate_data(
                to_type=backend_type,
                obsidian_path=obsidian_path,
                merge=True,
            )
            migrated = result.get("migrated", 0)
        except Exception as e:
            return {"ok": False, "error": f"迁移失败：{e}"}

    try:
        import config as _cfg
        _cfg.save_user_config({
            "memory": {
                "backend":       backend_type,
                "obsidian_vault": obsidian_path,
            }
        })
        _cfg.MEMORY_BACKEND  = backend_type
        _cfg.OBSIDIAN_VAULT  = obsidian_path
    except Exception as e:
        return {"ok": False, "error": f"保存配置失败：{e}"}

    _backend = None        # 下次调用 get_backend() 时重新实例化
    invalidate_cache()

    status = get_backend().get_status()
    return {
        "ok":      True,
        "backend": backend_type,
        "migrated": migrated,
        "status":  status,
    }


def migrate_data(to_type: str,
                 obsidian_path: str = "",
                 merge: bool = True) -> dict:
    """
    将当前后端的数据迁移到目标后端（不切换激活后端）。
    返回 {"ok": True, "migrated": N}
    """
    current = get_backend()
    snapshot = current.export_snapshot()

    if to_type == "obsidian" and obsidian_path:
        from memory_obsidian import ObsidianMemoryBackend
        target: MemoryBackend = ObsidianMemoryBackend(
            Path(obsidian_path).expanduser()
        )
    else:
        from memory_sqlite import SQLiteMemoryBackend
        target = SQLiteMemoryBackend()

    count = target.import_snapshot(snapshot, merge=merge)
    return {"ok": True, "migrated": count, "to": to_type}


# ── Agent 调用接口（向后兼容）─────────────────────────────────────

def get_memory_injection(agent_id: str) -> str:
    """获取注入到 system prompt 的记忆文本（带 5min 缓存）"""
    now = time.time()
    cached = _INJECT_CACHE.get(agent_id)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    result = get_backend().read_for_agent(agent_id)
    _INJECT_CACHE[agent_id] = (now, result)
    return result


def get_memory_self_description(agent_id: str = "") -> str:
    """记忆自述块：让人格如实回答「你的记忆存在哪」。
    所有信息从真实配置/后端读取，绝不编造。注入到 system prompt 末尾。"""
    try:
        from config import DATA_DIR
        st = get_backend().get_status()
        btype = st.get("type", "sqlite")
        if btype == "obsidian":
            loc = st.get("vault_path", "")
            store_line = f"长期记忆：Obsidian 笔记库（{loc}），都是普通 Markdown，可直接打开编辑"
        else:
            loc = st.get("db_path", "")
            store_line = f"长期记忆：本地数据库（{loc}），守藏每天夜里整理归档"
        entries = st.get("entries", 0)
        return (
            "\n\n## 关于「我的记忆」——用户问起时，照实说，别含糊\n"
            "我的记忆和全部数据都只存在用户本地这台电脑，从不上传云端。具体目录：\n"
            f"  {DATA_DIR}\n"
            "几处核心：\n"
            f"  · {store_line}（当前约 {entries} 条）\n"
            "  · 技能库与成长记录：skills/\n"
            "  · 成就与灵犀：economy.json\n"
            "  · 会话记录：sessions.db\n"
            "这些都是用户的东西——随时可以打开看、改、或删；想清空或导出，去「设置 → 数据」。\n"
            "回答这类问题时要坦诚、具体、让用户安心，不要泛泛说「存在本地」就完事。"
        )
    except Exception:
        return ""


def write_memory(key: str,
                 value: str,
                 category: str = "general",
                 agent_id: Optional[str] = None,
                 importance: int = 3) -> str:
    """写入一条记忆，返回 entry id"""
    eid = get_backend().write(key, value, category, agent_id, importance)
    invalidate_cache(agent_id)
    return eid


def search_memory(query: str,
                  agent_id: Optional[str] = None,
                  limit: int = 10) -> list[MemoryEntry]:
    return get_backend().search(query, agent_id, limit)


def list_memory(agent_id: Optional[str] = None) -> list[MemoryEntry]:
    return get_backend().list_all(agent_id)


def delete_memory(entry_id: str) -> bool:
    result = get_backend().delete(entry_id)
    invalidate_cache()
    return result


# ── 项目上下文（保持向后兼容）───────────────────────────────────

_ACTIVE_PROJECT_FILE = Path.home() / ".anima" / "data" / "active_project.json"


def get_active_project() -> Optional[str]:
    try:
        if _ACTIVE_PROJECT_FILE.exists():
            return json.loads(
                _ACTIVE_PROJECT_FILE.read_text("utf-8")
            ).get("project")
    except Exception:
        pass
    return None


def set_active_project(project_name: Optional[str]):
    _ACTIVE_PROJECT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "project":    project_name,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _ACTIVE_PROJECT_FILE.write_text(
        json.dumps(data, ensure_ascii=False), "utf-8"
    )
    invalidate_cache()


def get_project_context(project_name: str) -> str:
    """获取项目上下文：Obsidian 后端用文件，SQLite 后端用 category=project 的条目"""
    backend = get_backend()
    if backend.get_backend_type() == "obsidian":
        return backend.get_project_context(project_name)  # type: ignore[attr-defined]
    # SQLite：查找 category=project、key 包含项目名的条目
    entries = backend.list_all()
    proj_entries = [
        e for e in entries
        if e.category == "project" and project_name.lower() in e.key.lower()
    ]
    if not proj_entries:
        return ""
    lines = [f"- {e.key}：{e.value}" for e in proj_entries]
    return f"\n\n## 当前项目：{project_name}\n" + "\n".join(lines)


def get_active_project_context() -> str:
    active = get_active_project()
    return get_project_context(active) if active else ""


def list_projects() -> list[dict]:
    backend = get_backend()
    if backend.get_backend_type() == "obsidian":
        projects = backend.list_projects()  # type: ignore[attr-defined]
    else:
        # SQLite：从 category=project 的条目提取项目名
        entries = backend.list_all()
        seen: set[str] = set()
        projects = []
        for e in entries:
            if e.category != "project":
                continue
            pname = e.key.split("/")[0]
            if pname not in seen:
                seen.add(pname)
                projects.append({
                    "name":        pname,
                    "description": e.value[:100],
                    "files":       0,
                })
    active = get_active_project()
    for p in projects:
        p["is_active"] = p["name"] == active
    return projects


def create_project(project_name: str, description: str = "") -> dict:
    backend = get_backend()
    if backend.get_backend_type() == "obsidian":
        return backend.create_project(project_name, description)  # type: ignore[attr-defined]
    # SQLite：写一条 project 类型的记忆条目
    existing = [p for p in list_projects() if p["name"] == project_name]
    if existing:
        return {"ok": False, "error": f"项目 '{project_name}' 已存在"}
    backend.write(
        key=f"{project_name}/description",
        value=description or "待填写",
        category="project",
        importance=4,
    )
    return {"ok": True, "name": project_name}
