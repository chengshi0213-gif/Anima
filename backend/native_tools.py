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

import ipaddress
import json as _json
import socket
import urllib.error
import urllib.request
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
