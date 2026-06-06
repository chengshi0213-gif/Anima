#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地崩溃上报与诊断 — Anima
------------------------------------------------------------
隐私优先：所有内容只写本地，绝不外发。
  1. dump_exception() — 未捕获异常落盘到 ~/.anima/crashes/
  2. export_diagnostics() — 打包"诊断 zip"（日志+崩溃+系统信息+脱敏配置），
     供内测用户手动发给开发者反馈

关键安全约束：
  - 诊断包里的日志与配置都经过 _scrub() 脱敏，移除任何疑似 API Key / Token
  - config.yaml 即使含密文也整体不收录，只收录脱敏后的结构骨架
"""
import datetime
import json
import logging
import os
import platform
import re
import sys
import traceback
import zipfile
from pathlib import Path

log = logging.getLogger("anima.crash")

# 脱敏正则：sk-xxx、长 token、Bearer、enc:v1: 密文等
_SCRUB_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{6,})"),
    re.compile(r"(enc:v1:[A-Za-z0-9_\-=]+)"),
    re.compile(r"(Bearer\s+[A-Za-z0-9_\-\.=]+)", re.IGNORECASE),
    re.compile(r"([A-Za-z0-9_\-]{32,})"),   # 任意 32+ 长串（多为 key/token）
]


def _home() -> Path:
    return Path.home() / ".anima"


def _crash_dir() -> Path:
    d = _home() / "crashes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scrub(text: str) -> str:
    """移除疑似密钥/令牌，避免诊断包泄露凭证。"""
    if not isinstance(text, str):
        text = str(text)
    out = text
    for pat in _SCRUB_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def _system_info() -> dict:
    info = {
        "time": datetime.datetime.now().isoformat(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "machine": platform.machine(),
        "frozen": bool(getattr(sys, "frozen", False)),
    }
    try:
        import config as _cfg
        info["anima_home"] = str(getattr(_cfg, "_anima_home", ""))
        info["port_ws"] = getattr(_cfg, "PORT_WS", None)
    except Exception:
        pass
    return info


# ── 1. 崩溃落盘 ───────────────────────────────────────────────
def dump_exception(exc_type, exc_value, exc_tb, context: str = "") -> str | None:
    """把一个未捕获异常写成崩溃报告文件，返回路径。"""
    try:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = _crash_dir() / f"crash_{ts}.txt"
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        body = [
            "Anima 崩溃报告",
            "=" * 60,
            json.dumps(_system_info(), ensure_ascii=False, indent=2),
        ]
        if context:
            body.append(f"\n上下文: {context}")
        body.append("\nTraceback:")
        body.append(_scrub(tb))
        path.write_text("\n".join(body), encoding="utf-8")
        _prune_crashes(keep=20)
        log.info("崩溃报告已写入: %s", path)
        return str(path)
    except Exception as e:
        log.error("写崩溃报告失败: %s", e)
        return None


def dump_message(message: str, context: str = "") -> str | None:
    """非异常的严重错误主动记录。"""
    try:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = _crash_dir() / f"error_{ts}.txt"
        body = [
            "Anima 错误记录",
            "=" * 60,
            json.dumps(_system_info(), ensure_ascii=False, indent=2),
            f"\n上下文: {context}" if context else "",
            "\n消息:",
            _scrub(message),
        ]
        path.write_text("\n".join(body), encoding="utf-8")
        _prune_crashes(keep=20)
        return str(path)
    except Exception as e:
        log.error("写错误记录失败: %s", e)
        return None


def _prune_crashes(keep: int = 20) -> None:
    """只保留最近 keep 个崩溃文件。"""
    try:
        files = sorted(_crash_dir().glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass


def list_crashes() -> list:
    """列出崩溃文件（路径 + 时间 + 大小），供设置页展示。"""
    try:
        files = sorted(_crash_dir().glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [
            {
                "name": p.name,
                "time": datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                "size": p.stat().st_size,
            }
            for p in files
        ]
    except Exception:
        return []


# ── 2. 诊断包导出 ─────────────────────────────────────────────
def export_diagnostics(frontend_errors=None, dest_dir: str = "") -> dict:
    """
    打包诊断 zip：日志（脱敏）+ 崩溃文件 + 系统信息 + 前端错误队列 + 配置骨架（脱敏）。
    返回 {ok, path, error}。
    """
    try:
        out_dir = Path(dest_dir) if dest_dir else (_home() / "diagnostics")
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = out_dir / f"anima-diagnostics-{ts}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 系统信息
            zf.writestr("system_info.json",
                        json.dumps(_system_info(), ensure_ascii=False, indent=2))

            # 日志文件（脱敏）
            try:
                from config import LOG_DIR
                log_dir = Path(LOG_DIR)
            except Exception:
                log_dir = _home() / "data" / "logs"
            for name in ("anima.log", "anima.error.log"):
                fp = log_dir / name
                if fp.exists():
                    try:
                        # 只取末尾 ~500KB，避免诊断包过大
                        data = fp.read_text(encoding="utf-8", errors="replace")
                        if len(data) > 500_000:
                            data = data[-500_000:]
                        zf.writestr(f"logs/{name}", _scrub(data))
                    except Exception as e:
                        zf.writestr(f"logs/{name}.error", str(e))

            # 崩溃文件（已在写入时脱敏）
            for cf in _crash_dir().glob("*.txt"):
                try:
                    zf.write(cf, f"crashes/{cf.name}")
                except Exception:
                    pass

            # 前端错误队列
            if frontend_errors is not None:
                try:
                    txt = json.dumps(frontend_errors, ensure_ascii=False, indent=2)
                    zf.writestr("frontend_errors.json", _scrub(txt))
                except Exception as e:
                    zf.writestr("frontend_errors.error", str(e))

            # 配置骨架（脱敏：只保留键结构，敏感值打码）
            try:
                zf.writestr("config_skeleton.json",
                            json.dumps(_config_skeleton(), ensure_ascii=False, indent=2))
            except Exception:
                pass

        log.info("诊断包已导出: %s", zip_path)
        return {"ok": True, "path": str(zip_path)}
    except Exception as e:
        log.error("导出诊断包失败: %s", e)
        return {"ok": False, "error": str(e)}


def _config_skeleton() -> dict:
    """返回配置的键结构，敏感值一律打码，非敏感值保留（便于排查端口/路径问题）。"""
    try:
        import secret_box
        import config as _cfg
        raw = getattr(_cfg, "_cfg", {}) or {}

        def _walk(node):
            if isinstance(node, dict):
                return {
                    k: ("[REDACTED]" if (secret_box.looks_sensitive(k) or secret_box.is_encrypted(v))
                        else _walk(v))
                    for k, v in node.items()
                }
            if isinstance(node, list):
                return [_walk(x) for x in node]
            return node

        return _walk(raw)
    except Exception as e:
        return {"error": str(e)}
