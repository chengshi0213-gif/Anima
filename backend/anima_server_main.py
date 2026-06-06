#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anima 后端入口 — PyInstaller 打包时使用此文件
修复：中文路径 + 空格路径下 PyInstaller tmpdir 乱码问题
"""
import sys
import os
from pathlib import Path

# ── 修复 PyInstaller 在中文/空格路径下的 tmp 目录问题 ──────────────
# PyInstaller 解压到系统 TEMP 时，中文路径会导致 import 失败
_ANIMA_tmp = Path.home() / ".anima" / "tmp"
_ANIMA_tmp.mkdir(parents=True, exist_ok=True)
os.environ["TMPDIR"]  = str(_ANIMA_tmp)   # Unix
os.environ["TEMP"]    = str(_ANIMA_tmp)   # Windows
os.environ["TMP"]     = str(_ANIMA_tmp)   # Windows fallback

# 修复 Windows 控制台编码（防止中文路径 print 乱码）
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    # 设置控制台代码页为 UTF-8
    os.system("chcp 65001 >nul 2>&1")

# ── 确保能找到同目录的模块（PyInstaller 打包后路径不同）──
if getattr(sys, 'frozen', False):
    _dir = Path(sys.executable).parent
    # PyInstaller: _MEIPASS 是解压目录
    _mei = getattr(sys, '_MEIPASS', None)
    if _mei:
        sys.path.insert(0, str(_mei))
else:
    _dir = Path(__file__).parent

sys.path.insert(0, str(_dir))

# ── 在 Windows 打包版本中，可选隐藏控制台窗口 ──
# （注意：调试时建议保留控制台，发布时再启用）
# if sys.platform == "win32" and getattr(sys, 'frozen', False):
#     import ctypes
#     ctypes.windll.kernel32.FreeConsole()

# ── 初始化中央日志（尽早，在导入业务模块之前）──
try:
    from log_config import setup_logging
    setup_logging()
except Exception as _e:
    print(f"[Anima] 日志初始化失败（降级为 print）: {_e}")

from websocket_server import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
