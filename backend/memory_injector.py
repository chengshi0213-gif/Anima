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

import difflib
import json
import logging
import math
import time
from pathlib import Path
from typing import Optional

from memory_backend import (
    AGENT_MEMORY_CATEGORIES,
    DEFAULT_INJECTION,
    INJECTION_TEMPLATES,
    MemoryBackend,
    MemoryEntry,
)

_log = logging.getLogger(__name__)

# ── 单例 & 候选条目缓存 ──────────────────────────────────────────
_backend: Optional[MemoryBackend] = None
_INJECT_CACHE: dict[str, tuple[float, list[MemoryEntry]]] = {}   # agent_id → (ts, entries)
_CACHE_TTL = 300   # 5 分钟

# ── M5 分层注入预算 ──────────────────────────────────────────────
PROFILE_CHAR_BUDGET = 300      # 画像层（身份恒定）：always-on
TOPIC_CHAR_BUDGET = 900        # 话题相关：按复合分排序
FALLBACK_CHAR_BUDGET = 300     # 高重要性兜底：未被前两层覆盖的重要记忆
FALLBACK_MIN_IMPORTANCE = 4
RECENCY_HALFLIFE_DAYS = 30.0   # 新近度半衰期
STALE_ARCHIVE_DAYS = 180       # M7：C 状态层超过此天数未访问则归档

# ── M3 写入质量闸门 ──────────────────────────────────────────────
KEY_MERGE_THRESHOLD = 0.6        # 同 category 下 key 相似度 ≥ 此值视为近义，走 upsert
MIN_IMPORTANCE_FOR_WRITE = 2     # 非 A/D 层 importance 低于此值不写
MAX_WRITES_PER_SESSION = 8       # 单次 run() 内 remember 写入条数上限

# ── M2b 每周升格（L1 事实 → L2 画像洞察）────────────────────────
L2_SOURCE_SEP = "｜来源："        # value 中分隔"洞察文本"与"来源事实ID"的标记
L2_MAX_ENTRIES = 12              # 画像层 L2 条数上限，超出按"重要度+新近度"淘汰最弱的

_SESSION_WRITE_COUNT: dict[str, int] = {}   # agent_id → 本会话已写入条数


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


def reset_session_writes(agent_id: Optional[str] = None):
    """每次 AgentBase.run() 开始时调用，重置该 Agent 的单会话写入计数（M3）。"""
    if agent_id:
        _SESSION_WRITE_COUNT.pop(agent_id, None)
    else:
        _SESSION_WRITE_COUNT.clear()


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

def _get_candidate_entries(agent_id: str) -> list[MemoryEntry]:
    """该 Agent 可见的全部候选记忆（带 5min 缓存）。"""
    now = time.time()
    cached = _INJECT_CACHE.get(agent_id)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    entries = get_backend().list_all(agent_id)
    _INJECT_CACHE[agent_id] = (now, entries)
    return entries


def _recency_score(entry: MemoryEntry) -> float:
    """M7：新近度分数，优先用 last_accessed（被注入/检索的时间），回退到 updated_at。"""
    ts_str = entry.last_accessed or entry.updated_at
    try:
        ts = time.mktime(time.strptime(ts_str, "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0.0
    days = max(0.0, (time.time() - ts) / 86400)
    return math.exp(-days / RECENCY_HALFLIFE_DAYS)


def _importance_score(importance: int) -> float:
    return max(0.0, min(1.0, importance / 5.0))


def _relative_time(updated_at: str) -> str:
    """M8 式③（时间感）：把时间戳换算成中文相对时间，如"昨天""3天前""2个月前"。
    解析失败时返回空串，调用方据此跳过括注。"""
    try:
        ts = time.mktime(time.strptime(updated_at, "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return ""
    days = int((time.time() - ts) / 86400)
    if days <= 0:
        return "今天"
    if days == 1:
        return "昨天"
    if days < 7:
        return f"{days}天前"
    if days < 30:
        return f"{days // 7}周前"
    if days < 365:
        return f"{days // 30}个月前"
    return f"{days // 365}年前"


def _display_value(value: str) -> str:
    """M2b：L2 画像洞察的 value 里带「｜来源：id1,id2」标注（供审计/纠错），
    注入给人格的文本里隐去，只展示洞察本身。"""
    return value.split(L2_SOURCE_SEP, 1)[0]


def _format_entry_line(e: MemoryEntry, with_time: bool = False) -> str:
    value = _display_value(e.value)
    if with_time:
        rel = _relative_time(e.updated_at)
        if rel:
            return f"- {e.key}：{value}（{rel}）"
    return f"- {e.key}：{value}"


def _select_by_budget(entries: list[MemoryEntry], max_chars: int) -> list[MemoryEntry]:
    """按字数预算贪心选取，至少收录第一条（避免预算过小导致整层空白）。"""
    selected: list[MemoryEntry] = []
    total = 0
    for e in entries:
        line_len = len(e.key) + len(e.value) + 3
        if selected and total + line_len > max_chars:
            break
        selected.append(e)
        total += line_len
    return selected


def _score_topic_relevance(entries: list[MemoryEntry],
                           query: str,
                           agent_id: str) -> list[tuple[MemoryEntry, dict]]:
    """复合分 = 相关性(M4 余弦) + 新近度 + 重要性，三项均归一到 [0,1]，按复合分降序返回。"""
    relevance_map: dict[str, float] = {}
    backend = get_backend()
    if query and entries and hasattr(backend, "vector_search"):
        try:
            hits = backend.vector_search(query, agent_id=agent_id,
                                          limit=len(entries), min_score=0.0)
            relevance_map = {e.id: max(0.0, s) for e, s in hits}
        except Exception:
            relevance_map = {}

    scored = []
    for e in entries:
        relevance = relevance_map.get(e.id, 0.0)
        recency = _recency_score(e)
        importance = _importance_score(e.importance)
        scored.append((e, {
            "relevance": relevance,
            "recency": recency,
            "importance": importance,
            "composite": relevance + recency + importance,
        }))
    scored.sort(key=lambda x: -x[1]["composite"])
    return scored


def get_memory_injection(agent_id: str, query: str = "") -> str:
    """获取注入到 system prompt 的记忆文本（M5：分层预算 + 复合分排序）。

    三层预算：
      - 画像层（身份恒定，category A / user_profile）：always-on，~PROFILE_CHAR_BUDGET 字
      - 话题相关：按"相关性(M4余弦)+新近度+重要性"复合分排序，~TOPIC_CHAR_BUDGET 字
      - 高重要性兜底：importance >= FALLBACK_MIN_IMPORTANCE 且未被前两层覆盖，~FALLBACK_CHAR_BUDGET 字

    query 为当前用户输入（话题），用于 M4 语义相关性打分；为空或 embedding
    不可用时，相关性退化为 0，复合分退化为"新近度+重要性"，不报错。
    """
    cats = AGENT_MEMORY_CATEGORIES.get(agent_id, ["user_profile", "general"])
    entries = [e for e in _get_candidate_entries(agent_id) if e.category in cats]
    if not entries:
        return ""

    # 1. 画像层：身份恒定信息（A）+ 升格洞察（M2b L2），always-on
    profile_pool = sorted(
        (e for e in entries if e.category in ("A", "user_profile", "L2")),
        key=lambda e: -e.importance,
    )
    profile_sel = _select_by_budget(profile_pool, PROFILE_CHAR_BUDGET)
    used_ids = {e.id for e in profile_sel}

    # 2. 话题相关：复合分排序
    remaining = [e for e in entries if e.id not in used_ids]
    scored = _score_topic_relevance(remaining, query, agent_id)
    if _log.isEnabledFor(logging.DEBUG):
        for e, s in scored[:10]:
            _log.debug(
                "[M5 记忆注入] %s | 相关性=%.3f 新近度=%.3f 重要性=%.3f → 复合分=%.3f",
                e.key, s["relevance"], s["recency"], s["importance"], s["composite"],
            )
    topic_sel = _select_by_budget([e for e, _ in scored], TOPIC_CHAR_BUDGET)
    used_ids |= {e.id for e in topic_sel}

    # 3. 高重要性兜底：避免话题不匹配时丢掉关键信息
    fallback_pool = sorted(
        (e for e in entries
         if e.id not in used_ids and e.importance >= FALLBACK_MIN_IMPORTANCE),
        key=lambda e: -e.importance,
    )
    fallback_sel = _select_by_budget(fallback_pool, FALLBACK_CHAR_BUDGET)

    parts: list[str] = []
    if profile_sel:
        parts.append("[画像]\n" + "\n".join(_format_entry_line(e) for e in profile_sel))
    if topic_sel:
        parts.append("[相关记忆]\n" + "\n".join(_format_entry_line(e, with_time=True) for e in topic_sel))
    if fallback_sel:
        parts.append("[重要提醒]\n" + "\n".join(_format_entry_line(e, with_time=True) for e in fallback_sel))

    if not parts:
        return ""

    # M7：记录本次注入涉及的条目，刷新 last_accessed
    all_injected = profile_sel + topic_sel + fallback_sel
    if all_injected:
        backend = get_backend()
        if hasattr(backend, "touch_accessed"):
            try:
                backend.touch_accessed([e.id for e in all_injected])
            except Exception:
                pass

    template = INJECTION_TEMPLATES.get(agent_id, DEFAULT_INJECTION)
    return template.format(memory="\n\n".join(parts))


def get_due_reminders(agent_id: str, within_days: int = 1) -> list[MemoryEntry]:
    """M8 式④（主动想起）：该 Agent 即将/已经到期的提醒（remind_at <= 今天 + within_days）。
    后端不支持 due_reminders 时返回空列表，不报错。"""
    backend = get_backend()
    if not hasattr(backend, "due_reminders"):
        return []
    try:
        return backend.due_reminders(agent_id=agent_id, within_days=within_days)
    except Exception:
        return []


def format_due_reminders(agent_id: str, within_days: int = 1) -> str:
    """M8 式④：把到期提醒格式化成可直接拼进每日 SOP 提示词的文本；无到期项返回空串。"""
    entries = get_due_reminders(agent_id, within_days)
    if not entries:
        return ""
    lines = [f"- {e.key}：{e.value}（提醒日期：{e.remind_at}）" for e in entries]
    return "【临近的事，找机会自然提一句】\n" + "\n".join(lines)


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
            store_line = f"长期记忆：本地数据库（{loc}），Anima 每天整理归档"
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
                 importance: int = 3,
                 remind_at: Optional[str] = None) -> str:
    """写入一条记忆，返回 entry id（不经过 M3 闸门，供 SOP/导入/管理类直写场景）"""
    eid = get_backend().write(key, value, category, agent_id, importance, remind_at)
    invalidate_cache(agent_id)
    return eid


# ── M3 写入质量闸门 ──────────────────────────────────────────────

def _key_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _values_compatible(old_value: str, new_value: str) -> bool:
    """新值是否与旧值"兼容"（相同或互为补充），而非矛盾改写。"""
    o, n = old_value.strip(), new_value.strip()
    if o == n:
        return True
    return o in n or n in o


def _find_existing_entry(key: str,
                         category: str,
                         agent_id: Optional[str]) -> tuple[Optional[MemoryEntry], bool]:
    """找写入目标条目：先找精确同 key（任意 category，对齐后端 upsert 语义），
    再在同 category 下找最相似的 key。返回 (条目或None, 是否精确key命中)。"""
    entries = get_backend().list_all(agent_id)
    norm_key = key.strip().lower()
    for e in entries:
        if e.key.strip().lower() == norm_key:
            return e, True

    best: Optional[MemoryEntry] = None
    best_score = 0.0
    for e in entries:
        if e.category != category:
            continue
        score = _key_similarity(e.key, key)
        if score > best_score:
            best, best_score = e, score
    if best is not None and best_score >= KEY_MERGE_THRESHOLD:
        return best, False
    return None, False


def write_memory_gated(key: str,
                       value: str,
                       category: str = "general",
                       agent_id: Optional[str] = None,
                       importance: int = 3,
                       remind_at: Optional[str] = None) -> dict:
    """记忆写入闸门（M3）——供 remember 等会话内写入路径使用。

    依次校验：
      1. importance 过滤：低于 MIN_IMPORTANCE_FOR_WRITE 且非 A/D 层不写
      2. 单会话写入条数上限：超过 MAX_WRITES_PER_SESSION 不写
      3. 近义 key 合并：同 category 下相似 key 走 upsert 而非新建
      4. 冲突检测：新旧值矛盾时不静默覆盖，返回冲突信息

    remind_at（M8 式④）：可选的到期提醒日期 "YYYY-MM-DD"，随写入一并落库。

    返回：
      成功 {"ok": True, "id": str, "key": str, "merged": bool}
      拦截 {"ok": False, "reason": "low_importance"|"session_limit"|"conflict", ...}
    """
    if importance < MIN_IMPORTANCE_FOR_WRITE and category not in ("A", "D"):
        return {"ok": False, "reason": "low_importance",
                "message": f"重要度 {importance} 偏低且非 A/D 层，未写入"}

    session_key = agent_id or "_global"
    count = _SESSION_WRITE_COUNT.get(session_key, 0)
    if count >= MAX_WRITES_PER_SESSION:
        return {"ok": False, "reason": "session_limit",
                "message": f"本次对话已写入 {count} 条记忆，达到单会话上限（{MAX_WRITES_PER_SESSION}）"}

    existing, exact = _find_existing_entry(key, category, agent_id)
    merged = False
    if existing is not None:
        if not _values_compatible(existing.value, value):
            return {"ok": False, "reason": "conflict",
                    "existing_key": existing.key,
                    "existing_value": existing.value,
                    "new_value": value,
                    "message": (f"「{existing.key}」之前记的是「{existing.value}」，"
                                 f"现在是「{value}」，对不上")}
        if not exact:
            key = existing.key
            merged = True

    eid = get_backend().write(key, value, category, agent_id, importance, remind_at)
    _SESSION_WRITE_COUNT[session_key] = count + 1
    if agent_id:
        _INJECT_CACHE.pop(agent_id, None)
    else:
        _INJECT_CACHE.clear()
    return {"ok": True, "id": eid, "key": key, "merged": merged}


# ── M2b 每周升格：L1 事实 → L2 画像洞察 ──────────────────────────

def _find_existing_l2(key: str, agent_id: Optional[str]) -> Optional[MemoryEntry]:
    """在该 Agent 可见的 L2 条目里找同 key 或近义 key（用于合并而非新增）。"""
    l2_entries = [e for e in get_backend().list_all(agent_id) if e.category == "L2"]
    norm_key = key.strip().lower()
    for e in l2_entries:
        if e.key.strip().lower() == norm_key:
            return e
    best: Optional[MemoryEntry] = None
    best_score = 0.0
    for e in l2_entries:
        score = _key_similarity(e.key, key)
        if score > best_score:
            best, best_score = e, score
    return best if best_score >= KEY_MERGE_THRESHOLD else None


def _evict_excess_l2(agent_id: Optional[str]) -> list[str]:
    """画像层 L2 条数超过 L2_MAX_ENTRIES 时，淘汰"重要度最低、最久未更新"的条目。"""
    l2_entries = [e for e in get_backend().list_all(agent_id) if e.category == "L2"]
    if len(l2_entries) <= L2_MAX_ENTRIES:
        return []
    l2_entries.sort(key=lambda e: (e.importance, e.updated_at))
    to_evict = l2_entries[: len(l2_entries) - L2_MAX_ENTRIES]
    for e in to_evict:
        get_backend().delete(e.id)
    return [e.key for e in to_evict]


def write_l2_insight(key: str,
                     value: str,
                     agent_id: Optional[str] = None,
                     importance: int = 4,
                     source_ids: Optional[list[str]] = None) -> dict:
    """M2b：写入/更新一条 L2 画像洞察（每周升格 SOP 专用）。

    - 来源事实 ID 以「｜来源：id1,id2」附在 value 末尾，注入时自动隐去，
      仅供记忆列表/灵魂空间审计追溯。
    - 同 key 或近义 key 的已有 L2 条目会被更新（合并），不会重复新增。
    - 写入后若该 Agent 可见的 L2 条目数超过 L2_MAX_ENTRIES，自动淘汰
      "重要度最低、最久未更新"的条目，防画像膨胀。
    """
    full_value = value.strip()
    if source_ids:
        full_value += L2_SOURCE_SEP + ",".join(source_ids)

    existing = _find_existing_l2(key, agent_id)
    target_key = existing.key if existing else key
    merged = existing is not None

    eid = get_backend().write(target_key, full_value, "L2", agent_id, importance)
    evicted = _evict_excess_l2(agent_id)
    invalidate_cache(agent_id)

    return {"ok": True, "id": eid, "key": target_key, "merged": merged, "evicted": evicted}


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


# ── M7 遗忘与时效 ──────────────────────────────────────────────

def run_archival() -> dict:
    """归档超时 C 状态层记忆（M7）。由守藏每日 SOP 末尾调用即可，也可独立调。"""
    backend = get_backend()
    if not hasattr(backend, "archive_stale_c_layer"):
        return {"archived": 0, "reason": "backend_unsupported"}
    try:
        ids = backend.archive_stale_c_layer(days=STALE_ARCHIVE_DAYS)
        if ids:
            invalidate_cache()
        return {"archived": len(ids), "ids": ids}
    except Exception as e:
        return {"archived": 0, "error": str(e)}
