#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
invite.py — 邀请码引擎（Supabase 后端）

职责：
  verify_code    — 检查码是否有效（存在 / 未用 / 未过期）
  activate_code  — 激活码：标记已用、写 activations 表
  generate_codes — 为当前用户生成 N 个新邀请码（受配额限制）
  get_user_codes — 列出某用户生成的所有码及状态
  check_activated— 该用户是否已激活
  pending_rewards— 邀请人待领的「邀请成功」奖励数（用于灵犀联动）
  stats          — 管理员视角：总激活数、活跃邀请人排名
  get_user_token — 稳定用户/设备令牌（首次生成后持久化到 ~/.anima）

Supabase 真实表结构（public schema）：
  invite_codes(id, code[unique], created_by, created_at, used_by, used_at, expires_at)
  activations (id, invite_code, activated_at, referrer, user_token[unique])
  user_quota  (user_token[pk], codes_minted, max_codes)

连接信息由 config.py 读取 SUPABASE_URL / SUPABASE_ANON_KEY；
未配置则内置默认值。无 aiohttp 时所有接口优雅降级。
"""
from __future__ import annotations

import uuid
import secrets
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import aiohttp
    _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False

try:
    from config import SUPABASE_URL as _CFG_URL, SUPABASE_ANON_KEY as _CFG_KEY, DATA_DIR
    SUPABASE_URL = _CFG_URL or ""
    SUPABASE_KEY = _CFG_KEY or ""
    _DATA_DIR = DATA_DIR
except Exception:
    SUPABASE_URL = ""
    SUPABASE_KEY = ""
    _DATA_DIR = Path.home() / ".anima" / "data"

# 内置默认值（config.yaml / 环境变量均未设置时使用）
if not SUPABASE_URL:
    SUPABASE_URL = "https://zxlsmyzrskkcgmekszgh.supabase.co"
if not SUPABASE_KEY:
    SUPABASE_KEY = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inp4bHNteXpyc2trY2dtZWtzemdoIiwicm9sZSI6ImFub24i"
        "LCJpYXQiOjE3ODA0NTY0OTAsImV4cCI6MjA5NjAzMjQ5MH0"
        ".UO75grAPxHny-caznehcwsFTqGPjnFcWsZhXQ98f6yc"
    )

_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# 每用户默认可生成邀请码配额（与 user_quota.max_codes 默认一致）
DEFAULT_MAX_CODES = 3
# 新生成邀请码有效期（天）
CODE_TTL_DAYS = 30
# 使用码后获得的灵犀（被邀请人）
LINGXI_ON_USE = 20
# 邀请成功后邀请人获得的灵犀
LINGXI_ON_INVITE = 30
# 邀请奖励封顶次数
INVITE_CAP = 3

_TOKEN_FILE = Path.home() / ".anima" / "user_token.txt"


# ── 用户/设备令牌 ────────────────────────────────────────────────────

def get_user_token() -> str:
    """稳定用户令牌；首次调用自动生成并持久化到 ~/.anima/user_token.txt。"""
    if _TOKEN_FILE.exists():
        try:
            t = _TOKEN_FILE.read_text("utf-8").strip()
            if t:
                return t
        except Exception:
            pass
    t = "u_" + uuid.uuid4().hex
    try:
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(t, "utf-8")
    except Exception:
        pass
    return t


# 向后兼容别名（routes 早期用 get_device_id）
get_device_id = get_user_token


# ── Supabase REST 辅助 ────────────────────────────────────────────────

def _configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY and _HAS_AIOHTTP)


async def _sb_get(path: str, params: dict | None = None) -> list | None:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, headers=_HEADERS, params=params or {}) as r:
                if r.status >= 400:
                    return None
                return await r.json()
    except Exception:
        return None


async def _sb_post(path: str, body: dict) -> dict | None:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, headers=_HEADERS, json=body) as r:
                if r.status >= 400:
                    return None
                data = await r.json()
                return data[0] if isinstance(data, list) and data else data
    except Exception:
        return None


async def _sb_patch(path: str, match: dict, body: dict) -> bool:
    """PATCH（UPDATE WHERE）"""
    params = {k: f"eq.{v}" for k, v in match.items()}
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    h = {**_HEADERS, "Prefer": "return=minimal"}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.patch(url, headers=h, params=params, json=body) as r:
                return r.status < 300
    except Exception:
        return False


# ── 码生成 ───────────────────────────────────────────────────────────

def _make_code() -> str:
    """生成形如 ANIMA-AXJK-M7PQ 的可读邀请码（去掉易混字符）。"""
    alphabet = (string.ascii_uppercase.replace("O", "").replace("I", "")
                + string.digits.replace("0", "").replace("1", ""))
    raw = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"ANIMA-{raw[:4]}-{raw[4:]}"


def _is_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return exp < datetime.now(timezone.utc)
    except Exception:
        return False


# ── 公开 API ─────────────────────────────────────────────────────────

async def verify_code(code: str) -> dict:
    """
    检查码是否可用（不消耗）。
    返回 {"ok": bool, "reason": str}
      reason: valid / not_found / used / expired / not_configured
    """
    if not _configured():
        return {"ok": False, "reason": "not_configured"}
    code = code.strip().upper()
    rows = await _sb_get("invite_codes", {
        "code": f"eq.{code}",
        "select": "code,used_at,used_by,expires_at",
    })
    if not rows:
        return {"ok": False, "reason": "not_found"}
    row = rows[0]
    if row.get("used_at") or row.get("used_by"):
        return {"ok": False, "reason": "used"}
    if _is_expired(row.get("expires_at")):
        return {"ok": False, "reason": "expired"}
    return {"ok": True, "reason": "valid"}


async def activate_code(code: str, user_token: str | None = None) -> dict:
    """
    激活邀请码：
    1. 该用户未激活过（user_token unique）
    2. 校验码有效
    3. UPDATE invite_codes 标记 used_by/used_at
    4. INSERT activations(invite_code, user_token, referrer=邀请人)
    5. 确保 user_quota 记录存在
    返回 {"ok": bool, "reason": str, "inviter": str|None, "lingxi": int}
    """
    if not _configured():
        return {"ok": False, "reason": "not_configured"}
    code = code.strip().upper()
    user_token = user_token or get_user_token()

    # 该用户已激活过？（user_token 唯一）
    existing = await _sb_get("activations", {
        "user_token": f"eq.{user_token}",
        "select": "id",
        "limit": "1",
    })
    if existing:
        return {"ok": True, "reason": "already_activated", "inviter": None, "lingxi": 0}

    v = await verify_code(code)
    if not v["ok"]:
        return {"ok": False, "reason": v["reason"]}

    # 邀请人 = invite_codes.created_by
    rows = await _sb_get("invite_codes", {"code": f"eq.{code}", "select": "created_by"})
    inviter = rows[0].get("created_by") if rows else None

    now_iso = datetime.now(timezone.utc).isoformat()

    # 标记已用
    await _sb_patch("invite_codes", {"code": code}, {
        "used_by": user_token,
        "used_at": now_iso,
    })

    # 写激活记录
    rec = await _sb_post("activations", {
        "invite_code": code,
        "user_token": user_token,
        "referrer": inviter,
    })
    if rec is None:
        return {"ok": False, "reason": "activation_failed"}

    # 确保被邀请人有配额记录
    await _ensure_user_quota(user_token)

    # 本机用户作为被邀请人，本地发放 +20 灵犀（幂等）
    try:
        import economy as _ec
        _ec.grant(LINGXI_ON_USE, "invite_activated", "使用结缘码入门")
    except Exception:
        pass

    return {"ok": True, "reason": "activated", "inviter": inviter, "lingxi": LINGXI_ON_USE}


async def _ensure_user_quota(user_token: str) -> None:
    """确保 user_quota 有该用户记录。"""
    existing = await _sb_get("user_quota", {
        "user_token": f"eq.{user_token}",
        "select": "user_token",
        "limit": "1",
    })
    if not existing:
        await _sb_post("user_quota", {
            "user_token": user_token,
            "codes_minted": 0,
            "max_codes": DEFAULT_MAX_CODES,
        })


async def generate_codes(user_token: str | None = None, n: int = 1) -> dict:
    """
    为当前用户生成最多 n 个邀请码（受 max_codes - codes_minted 限制）。
    返回 {"ok": bool, "codes": [...], "remaining": int, "reason": str}
    """
    if not _configured():
        return {"ok": False, "reason": "not_configured", "codes": [], "remaining": 0}
    user_token = user_token or get_user_token()

    await _ensure_user_quota(user_token)
    quota_rows = await _sb_get("user_quota", {
        "user_token": f"eq.{user_token}",
        "select": "codes_minted,max_codes",
    })
    if not quota_rows:
        return {"ok": False, "reason": "quota_fetch_failed", "codes": [], "remaining": 0}

    q = quota_rows[0]
    minted = int(q.get("codes_minted") or 0)
    maxc   = int(q.get("max_codes") or DEFAULT_MAX_CODES)
    avail  = max(0, maxc - minted)
    if avail <= 0:
        return {"ok": False, "reason": "quota_exhausted", "codes": [], "remaining": 0}

    to_gen = min(n, avail)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=CODE_TTL_DAYS)).isoformat()
    new_codes: list[str] = []
    for _ in range(to_gen):
        code = _make_code()
        res = await _sb_post("invite_codes", {
            "code": code,
            "created_by": user_token,
            "expires_at": expires_at,
        })
        if res:
            new_codes.append(code)

    if new_codes:
        await _sb_patch("user_quota", {"user_token": user_token}, {
            "codes_minted": minted + len(new_codes),
        })

    return {
        "ok": bool(new_codes),
        "reason": "ok" if new_codes else "insert_failed",
        "codes": new_codes,
        "remaining": avail - len(new_codes),
    }


async def mint_code(created_by: str = "mailer", ttl_days: int = CODE_TTL_DAYS) -> str | None:
    """管理员/邮箱管家直接铸造一枚邀请码（不消耗任何用户配额）。返回码或 None。"""
    if not _configured():
        return None
    code = _make_code()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()
    res = await _sb_post("invite_codes", {
        "code": code,
        "created_by": created_by,
        "expires_at": expires_at,
    })
    return code if res else None


# ── 网页「申请结缘码」排队（云函数登记，本机邮箱管家发信）───────────────
#
# anima-site 是纯静态页面，没有自己的服务器；访客填邮箱后由一个云函数
# （Vercel serverless）把申请写进 Supabase 的 web_invite_requests 表
# （status=pending）。但 139 等国内邮箱会拒绝来自境外云服务器 IP 的发信
# 请求（实测 "450 Mail rejected"），所以真正的发信仍由本机（家庭 IP，
# 已端到端验证可用）的邮箱管家轮询这张表来完成，复用与邮件申请完全相同的
# 铸码 + SMTP 发信通道。

async def fetch_pending_web_invites(limit: int = 20) -> list[dict]:
    """拉取网页申请队列里待处理的条目（status=pending），按申请时间升序。"""
    if not _configured():
        return []
    rows = await _sb_get("web_invite_requests", {
        "status": "eq.pending",
        "select": "id,email,code,created_at",
        "order": "created_at.asc",
        "limit": str(limit),
    })
    return rows or []


async def mark_web_invite(req_id: int, status: str | None = None, code: str | None = None) -> bool:
    """更新网页申请队列条目（status 和/或 code，按需更新其一或两者都更新）。

    设计要点：发信失败（如邮箱服务商临时限流/反垃圾拒收）时【不要】标记为终态，
    应保持 pending 留给下一轮轮询重试；同时把已经铸造好的码先持久化在行上，
    重试时复用同一枚码，避免每次失败都白白多铸一枚。"""
    patch: dict = {}
    if status is not None:
        patch["status"] = status
        if status == "sent":
            patch["sent_at"] = datetime.now(timezone.utc).isoformat()
    if code is not None:
        patch["code"] = code
    if not patch:
        return True
    return await _sb_patch("web_invite_requests", {"id": req_id}, patch)


async def get_user_codes(user_token: str | None = None) -> dict:
    """
    列出某用户生成的所有邀请码及状态 + 配额。
    返回 {"ok": bool, "codes": [{code,is_used,expires_at,used_at}], "quota": {...}}
    """
    if not _configured():
        return {"ok": False, "reason": "not_configured", "codes": [], "quota": {}}
    user_token = user_token or get_user_token()

    raw = await _sb_get("invite_codes", {
        "created_by": f"eq.{user_token}",
        "select": "code,used_by,used_at,expires_at,created_at",
        "order": "created_at.desc",
    }) or []
    codes = [{
        "code": c.get("code"),
        "is_used": bool(c.get("used_at") or c.get("used_by")),
        "expired": _is_expired(c.get("expires_at")),
        "expires_at": c.get("expires_at"),
        "used_at": c.get("used_at"),
    } for c in raw]

    quota_rows = await _sb_get("user_quota", {
        "user_token": f"eq.{user_token}",
        "select": "codes_minted,max_codes",
    }) or []
    q = quota_rows[0] if quota_rows else {}
    maxc   = int(q.get("max_codes") or DEFAULT_MAX_CODES)
    minted = int(q.get("codes_minted") or 0)

    return {
        "ok": True,
        "codes": codes,
        "quota": {"total": maxc, "generated": minted, "remaining": max(0, maxc - minted)},
    }


async def check_activated(user_token: str | None = None) -> bool:
    """该用户是否已通过邀请码激活。未配置时放行（开发模式）。"""
    if not _configured():
        return True
    user_token = user_token or get_user_token()
    rows = await _sb_get("activations", {
        "user_token": f"eq.{user_token}",
        "select": "id",
        "limit": "1",
    })
    return bool(rows)


async def successful_invites(user_token: str | None = None) -> int:
    """该用户作为邀请人，成功邀请了多少人（activations.referrer = user_token）。"""
    if not _configured():
        return 0
    user_token = user_token or get_user_token()
    rows = await _sb_get("activations", {
        "referrer": f"eq.{user_token}",
        "select": "id",
    })
    return len(rows or [])


async def reconcile_invite_rewards(user_token: str | None = None) -> dict:
    """
    邀请人侧对账：查 Supabase 里 referrer=本机用户 的成功激活数，
    给邀请人补发尚未领取的 +30 灵犀（封顶 INVITE_CAP=3 次，幂等）。
    应在 App 启动 / 设置页打开时调用。
    返回 {"ok", "successful_invites", "granted_count", "lingxi"}
    """
    succ = await successful_invites(user_token)
    rewardable = min(succ, INVITE_CAP)
    granted = 0
    lingxi = 0
    try:
        import economy as _ec
        for i in range(1, rewardable + 1):
            res = _ec.grant(LINGXI_ON_INVITE, f"invite_reward_{i}", f"第{i}位好友因你结缘")
            if res.get("ok"):
                granted += 1
        lingxi = _ec.balance()
    except Exception:
        pass
    return {"ok": True, "successful_invites": succ, "granted_count": granted,
            "newly_granted_lingxi": granted * LINGXI_ON_INVITE, "lingxi": lingxi}


async def stats() -> dict:
    """管理员视角：激活总数、最近激活、邀请人排名（前 10）。"""
    if not _configured():
        return {"ok": False, "reason": "not_configured"}

    all_acts = await _sb_get("activations", {
        "select": "user_token,activated_at,invite_code,referrer",
        "order": "activated_at.desc",
    }) or []
    total = len(all_acts)
    recent = all_acts[:10]

    ranking: dict[str, int] = {}
    by_day_map: dict[str, int] = {}
    for a in all_acts:
        ref = a.get("referrer")
        if ref and ref != "admin":
            ranking[ref] = ranking.get(ref, 0) + 1
        ts = a.get("activated_at") or ""
        day = ts[:10]   # YYYY-MM-DD
        if day:
            by_day_map[day] = by_day_map.get(day, 0) + 1
    top = sorted(ranking.items(), key=lambda x: x[1], reverse=True)[:10]

    # 近 30 天连续曲线（补零）
    from datetime import date as _date, timedelta as _td
    today = _date.today()
    by_day = []
    for i in range(29, -1, -1):
        d = (today - _td(days=i)).isoformat()
        by_day.append({"date": d, "count": by_day_map.get(d, 0)})

    # 码的整体状态分布
    codes_rows = await _sb_get("invite_codes", {"select": "used_at,expires_at,created_by"}) or []
    used = sum(1 for c in codes_rows if c.get("used_at"))
    minted_total = len(codes_rows)

    return {
        "ok": True,
        "total_activations": total,
        "total_codes": minted_total,
        "used_codes": used,
        "unused_codes": minted_total - used,
        "recent": recent,
        "top_inviters": [{"user_token": t, "count": c} for t, c in top],
        "by_day": by_day,
    }
