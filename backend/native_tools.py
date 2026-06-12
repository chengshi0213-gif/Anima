#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
native_tools.py — v1.2.1 原生工具层（网络 / IO 类）

收纳与文件系统工具（_list_dir 等在 xi_worker.py）不同族的原生工具，供
capabilities.py（xi）与 executor_worker.py（executor）共享 import：

  T6 http_request  直调任意 REST API（安全版：拦截内网/环回 IP，防 SSRF）
  T5 read_pdf      （后续追加）
  T4 read_image    （后续追加）
  T3 install_pkg   （后续追加）
  T2 long_run/...  （后续追加）

设计：纯模块级函数，无副作用全局状态（long_run 的任务表除外，到时单列）。
"""
from __future__ import annotations

import base64
import ipaddress
import json as _json
import re
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

# ── T6: http_request（SSRF 安全版）────────────────────────────────────────────

_HTTP_TIMEOUT_DEFAULT = 30
_HTTP_MAX_TIMEOUT = 120
_HTTP_BODY_CAP = 100_000   # 返回正文截断上限，防 token 爆炸
_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}


def _host_is_internal(host: str) -> tuple[bool, str]:
    """解析主机名的所有 IP，任意一个落在私有/环回/链路本地/保留段即视为内网。
    返回 (is_internal, reason)。解析失败按「无法确认安全」从严拒绝。"""
    if not host:
        return True, "缺少主机名"
    if host.lower() in ("localhost", "localhost.localdomain"):
        return True, "localhost 被安全策略拦截"
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception as e:
        return True, f"主机名解析失败（无法确认安全）: {e}"
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return True, f"目标解析到内网/环回地址 {ip_str}，已拦截（防 SSRF）"
    return False, ""


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """重定向目标也要过内网拦截——防止公网 URL 302 跳到内网地址绕过 SSRF 闸门。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urlparse(newurl).hostname or ""
        internal, reason = _host_is_internal(host)
        if internal:
            raise urllib.error.HTTPError(
                newurl, code, f"重定向到内网地址被拦截: {reason}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirectHandler())


def _http_request(method: str, url: str, body=None,
                  headers: dict | None = None, timeout: int = 30) -> dict:
    """直调任意 REST API。安全版：只允许 http/https，拦截解析到内网/环回的 URL
    （含重定向目标）。body 为 dict/list 时按 JSON 发送（自动补 Content-Type），
    为 str 时原样发送。失败明确报错，不静默吞掉。"""
    method = (method or "GET").upper()
    if method not in _ALLOWED_METHODS:
        return {"error": f"不支持的 HTTP 方法: {method}"}
    try:
        parsed = urlparse(url)
    except Exception as e:
        return {"error": f"URL 解析失败: {e}"}
    if parsed.scheme not in ("http", "https"):
        return {"error": f"只允许 http/https，收到: {parsed.scheme or '(空)'}"}
    internal, reason = _host_is_internal(parsed.hostname or "")
    if internal:
        return {"error": reason + "。如确需访问本机服务，请改用 shell_run + curl。"}
    try:
        timeout = max(1, min(int(timeout), _HTTP_MAX_TIMEOUT))
    except Exception:
        timeout = _HTTP_TIMEOUT_DEFAULT

    data = None
    hdrs = dict(headers or {})
    if body is not None:
        if isinstance(body, (dict, list)):
            data = _json.dumps(body, ensure_ascii=False).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        else:
            data = str(body).encode("utf-8")
    hdrs.setdefault("User-Agent", "Anima/1.2.1")

    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read(_HTTP_BODY_CAP + 1)
            text = raw.decode("utf-8", errors="replace")
            return {
                "status": getattr(resp, "status", None) or resp.getcode(),
                "headers": dict(resp.headers),
                "body": text[:_HTTP_BODY_CAP],
                "truncated": len(raw) > _HTTP_BODY_CAP,
            }
    except urllib.error.HTTPError as e:
        # HTTP 错误码也回传正文——API 的错误说明常在 body 里
        try:
            text = e.read().decode("utf-8", errors="replace")[:_HTTP_BODY_CAP]
        except Exception:
            text = ""
        return {"status": e.code, "error": f"HTTP {e.code}", "body": text}
    except Exception as e:
        return {"error": str(e)}


# ── T5: read_pdf ─────────────────────────────────────────────────────────────

_PDF_TEXT_CAP = 80_000
_PDF_PAGE_WARN = 100


def _read_pdf(path: str, start_page: int | None = None,
              end_page: int | None = None) -> dict:
    """读取 PDF 文本内容。>100 页时必须指定页范围，防 token 爆炸。
    双 fallback：pdfminer.six（优先，排版更好）→ pypdf（兜底）。"""
    p = Path(path)
    if not p.exists():
        return {"error": f"文件不存在: {path}"}
    if not p.is_file():
        return {"error": f"不是文件: {path}"}
    suffix = p.suffix.lower()
    if suffix != ".pdf":
        return {"error": f"不是 PDF 文件（后缀 {suffix}）"}
    try:
        size_mb = p.stat().st_size / (1024 * 1024)
    except Exception:
        size_mb = 0
    if size_mb > 100:
        return {"error": f"文件过大（{size_mb:.1f}MB > 100MB），拒绝读取"}

    total_pages = _pdf_page_count(path)
    if total_pages is not None and total_pages > _PDF_PAGE_WARN:
        if start_page is None and end_page is None:
            return {"error": f"PDF 共 {total_pages} 页（> {_PDF_PAGE_WARN}），"
                    "请用 start_page/end_page 指定范围（如 1-20）"}

    text, method, error = _extract_pdfminer(path, start_page, end_page)
    if text is None:
        text, method, error = _extract_pypdf(path, start_page, end_page)
    if text is None:
        return {"error": f"PDF 解析失败: {error}。请确认文件未损坏且非纯扫描件。"}

    truncated = len(text) > _PDF_TEXT_CAP
    return {
        "text": text[:_PDF_TEXT_CAP],
        "truncated": truncated,
        "total_pages": total_pages,
        "method": method,
        "path": str(p),
    }


def _pdf_page_count(path: str) -> int | None:
    try:
        from pypdf import PdfReader
        return len(PdfReader(path).pages)
    except Exception:
        return None


def _extract_pdfminer(path: str, start: int | None, end: int | None
                      ) -> tuple[str | None, str, str]:
    try:
        from pdfminer.high_level import extract_text
        if start is not None or end is not None:
            s = max(0, (start or 1) - 1)
            e = end
            page_numbers = set(range(s, e)) if e else None
            text = extract_text(path, page_numbers=page_numbers)
        else:
            text = extract_text(path)
        if not text or not text.strip():
            return None, "pdfminer", "提取文本为空（可能是扫描件/图片 PDF）"
        return text, "pdfminer", ""
    except Exception as exc:
        return None, "pdfminer", str(exc)


def _extract_pypdf(path: str, start: int | None, end: int | None
                   ) -> tuple[str | None, str, str]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = reader.pages
        s = max(0, (start or 1) - 1)
        e = min(len(pages), end) if end else len(pages)
        parts = []
        for i in range(s, e):
            t = pages[i].extract_text()
            if t:
                parts.append(t)
        text = "\n".join(parts)
        if not text.strip():
            return None, "pypdf", "提取文本为空（可能是扫描件/图片 PDF）"
        return text, "pypdf", ""
    except Exception as exc:
        return None, "pypdf", str(exc)


# ── T4: read_image ───────────────────────────────────────────────────────────

_IMAGE_SIZE_CAP = 5 * 1024 * 1024  # 5MB
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
_MEDIA_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}


def _read_image(path: str) -> dict:
    """读取图片文件，返回 base64 编码 + vision content block。
    超 5MB 拒绝。返回的 _vision_block 字段供 agent_base 注入多模态消息。"""
    p = Path(path)
    if not p.exists():
        return {"error": f"文件不存在: {path}"}
    if not p.is_file():
        return {"error": f"不是文件: {path}"}
    ext = p.suffix.lower()
    if ext not in _IMAGE_EXTS:
        return {"error": f"不支持的图片格式: {ext}（支持 {', '.join(sorted(_IMAGE_EXTS))}）"}
    size = p.stat().st_size
    if size > _IMAGE_SIZE_CAP:
        return {"error": f"图片过大（{size / 1024 / 1024:.1f}MB > 5MB），拒绝读取"}
    if size == 0:
        return {"error": "文件为空"}
    try:
        raw = p.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        media_type = _MEDIA_TYPES.get(ext, "image/png")
        data_url = f"data:{media_type};base64,{b64}"
        return {
            "path": str(p),
            "size_bytes": size,
            "media_type": media_type,
            "_vision_block": [
                {"type": "text", "text": f"[图片: {p.name}, {size}B, {media_type}]"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    except Exception as e:
        return {"error": f"读取图片失败: {e}"}


# ── T3: install_pkg ──────────────────────────────────────────────────────────

_PKG_NAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._\-]*[A-Za-z0-9])?$")
_ALLOWED_MANAGERS = {"pip", "npm"}
_INSTALL_TIMEOUT = 120


def _install_pkg(package: str, manager: str = "pip") -> dict:
    """安装 Python/Node 包。仅允许官方源（pypi.org / npmjs.com），防供应链攻击。"""
    package = (package or "").strip()
    manager = (manager or "pip").strip().lower()
    if manager not in _ALLOWED_MANAGERS:
        return {"error": f"不支持的包管理器: {manager}（仅 pip/npm）"}
    if not package:
        return {"error": "包名不能为空"}
    if "--index-url" in package or "--registry" in package or "-i " in package:
        return {"error": "禁止指定自定义包源（安全策略：仅允许官方源）"}
    pkg_base = package.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
    if not _PKG_NAME_RE.match(pkg_base):
        return {"error": f"非法包名: {package!r}"}

    if manager == "pip":
        cmd = ["pip", "install", "--no-input", package]
    else:
        cmd = ["npm", "install", package]

    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_INSTALL_TIMEOUT,
        )
        return {
            "installed": r.returncode == 0,
            "package": package,
            "manager": manager,
            "stdout": r.stdout[-4000:] if len(r.stdout) > 4000 else r.stdout,
            "stderr": r.stderr[-2000:] if len(r.stderr) > 2000 else r.stderr,
            "exit_code": r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"安装超时（{_INSTALL_TIMEOUT}秒）", "package": package}
    except FileNotFoundError:
        return {"error": f"未找到 {manager} 命令，请确认已安装"}
    except Exception as e:
        return {"error": str(e)}
