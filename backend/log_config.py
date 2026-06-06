#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中央日志配置 — Anima
------------------------------------------------------------
统一全后端日志：格式、级别、文件轮转、未捕获异常落盘。

用法（在最早的入口处调用一次即可）：
    from log_config import setup_logging
    setup_logging()

之后任何模块照常 `logging.getLogger("xxx")` 即可，
不需要各自 basicConfig / addHandler。
"""
import logging
import logging.handlers
import os
import sys
from pathlib import Path

_CONFIGURED = False

# 统一格式：时间 | 级别 | 模块 | 消息
_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _resolve_log_dir() -> Path:
    """获取日志目录，优先用 config.LOG_DIR，失败则回退 ~/.anima/logs。"""
    try:
        from config import LOG_DIR  # 延迟导入，避免循环依赖
        return Path(LOG_DIR)
    except Exception:
        d = Path.home() / ".anima" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d


def setup_logging(level: int | None = None) -> Path:
    """
    初始化全局日志。幂等：重复调用不会重复添加 handler。

    Args:
        level: 日志级别，默认读环境变量 ANIMA_LOG_LEVEL（INFO/DEBUG/...），
               否则 INFO。

    Returns:
        日志目录路径。
    """
    global _CONFIGURED
    if _CONFIGURED:
        return _resolve_log_dir()

    if level is None:
        env = (os.environ.get("ANIMA_LOG_LEVEL") or "INFO").upper()
        level = getattr(logging, env, logging.INFO)

    log_dir = _resolve_log_dir()
    formatter = logging.Formatter(_FMT, datefmt=_DATEFMT)

    root = logging.getLogger()
    root.setLevel(level)

    # 1) 主日志文件（全部级别），10MB × 5 轮换
    try:
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "anima.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(formatter)
        root.addHandler(fh)
    except Exception as e:
        print(f"[log_config] 主日志文件初始化失败: {e}", file=sys.stderr)

    # 2) 错误日志文件（仅 WARNING+），便于快速定位问题
    try:
        eh = logging.handlers.RotatingFileHandler(
            log_dir / "anima.error.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        eh.setLevel(logging.WARNING)
        eh.setFormatter(formatter)
        root.addHandler(eh)
    except Exception as e:
        print(f"[log_config] 错误日志文件初始化失败: {e}", file=sys.stderr)

    # 3) 控制台（走 sidecar 管道，被 Tauri 收集）
    try:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(level)
        ch.setFormatter(formatter)
        root.addHandler(ch)
    except Exception as e:
        print(f"[log_config] 控制台日志初始化失败: {e}", file=sys.stderr)

    # 4) 把 Python warnings 也接进日志
    logging.captureWarnings(True)

    # 5) 未捕获异常落盘（线程 + 主线程 + asyncio）
    _install_excepthooks()

    _CONFIGURED = True
    logging.getLogger("anima").info("日志系统已就绪，目录: %s (级别=%s)",
                                     log_dir, logging.getLevelName(level))
    return log_dir


def _install_excepthooks() -> None:
    """把各种未捕获异常统一记进日志（不替换 Task #5 的崩溃落盘，互补）。"""
    log = logging.getLogger("anima.uncaught")

    # 主线程未捕获异常
    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.critical("未捕获异常", exc_info=(exc_type, exc_value, exc_tb))
        # 交给可选的崩溃上报模块（若存在）
        try:
            import crash_reporter
            crash_reporter.dump_exception(exc_type, exc_value, exc_tb)
        except Exception:
            pass

    sys.excepthook = _hook

    # 子线程未捕获异常（Python 3.8+）
    try:
        import threading

        def _thread_hook(args):
            if issubclass(args.exc_type, KeyboardInterrupt):
                return
            log.critical(
                "线程未捕获异常 (%s)",
                args.thread.name if args.thread else "?",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            try:
                import crash_reporter
                crash_reporter.dump_exception(
                    args.exc_type, args.exc_value, args.exc_traceback
                )
            except Exception:
                pass

        threading.excepthook = _thread_hook
    except Exception:
        pass
