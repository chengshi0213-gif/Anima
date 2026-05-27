"""
routes/auth.py — CORS 头、本地 Token 安全、鉴权中间件
"""
import secrets as _secrets
import ipaddress as _ipaddress
from pathlib import Path
from aiohttp import web

# ── CORS ──────────────────────────────────────────────
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def _json_error(message: str, status: int = 400) -> web.Response:
    """统一错误响应格式: {"error": "..."}，带 CORS 头"""
    return web.json_response({"error": message}, status=status, headers=CORS_HEADERS)


# ── 本地安全 Token ──────────────────────────────────────
_TOKEN_FILE = Path.home() / ".anima" / "local_token.txt"


def _load_or_create_token() -> str:
    if _TOKEN_FILE.exists():
        try:
            tok = _TOKEN_FILE.read_text("utf-8").strip()
            if len(tok) >= 32:
                return tok
        except Exception:
            pass
    tok = _secrets.token_urlsafe(32)
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(tok, "utf-8")
    return tok


LOCAL_TOKEN: str = _load_or_create_token()


def _is_local(request) -> bool:
    """判断是否为本地请求（127.x 或 ::1）"""
    peer = request.transport.get_extra_info("peername")
    if not peer:
        return True
    try:
        addr = _ipaddress.ip_address(peer[0])
        return addr.is_loopback
    except Exception:
        return True


def _check_token(request) -> bool:
    """非本地请求必须携带正确 token。本地请求始终放行。"""
    if _is_local(request):
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip() == LOCAL_TOKEN
    return False


@web.middleware
async def auth_middleware(request, handler):
    """鉴权中间件：OPTIONS 和 /health 跳过；其他非本地请求验证 token"""
    if request.method == "OPTIONS":
        return await handler(request)
    if request.path in ("/health", "/docs", "/openapi.json"):
        return await handler(request)
    if not _check_token(request):
        return web.json_response(
            {"error": "unauthorized — include Authorization: Bearer <local_token>"},
            status=401, headers=CORS_HEADERS,
        )
    return await handler(request)
