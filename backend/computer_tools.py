#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
computer_tools.py — 桌面操作工具层（截图 / 鼠标 / 键盘）+ 安全闸门

让人格在用户明确授权下操作本机桌面：截屏看内容、移动/点击鼠标、
键盘输入、热键、滚动。底层用 pyautogui（鼠标键盘）+ Pillow.ImageGrab（截屏）。

⚠️ 这是高权限能力，默认完全关闭。三道闸门保护用户：
  1. 总开关 + 模式（off / readonly / confirm / auto），存本机 ~/.anima/data/computer_use.json
       off      ：全部禁止（默认）
       readonly ：只允许截屏 / 读取屏幕信息，禁止一切控制
       confirm  ：读取放行；每个控制动作（点击/输入/热键/滚动）执行前
                  挂起等待用户在界面上逐个确认，超时默认拒绝
       auto     ：本次授权内放行全部动作（高级用户，界面会显著警示）
  2. pyautogui FAILSAFE：把鼠标猛甩到屏幕左上角即可中止一切自动操作。
  3. 全量审计：每个动作（含被拒）都写入 ~/.anima/data/computer_use_audit.jsonl。

被闸门拦下时抛 PermissionRequest，前端据此弹出授权卡片，引导用户去设置里开启，
而不是静默失败——符合"用户简单做到"的产品取向。

诚实说明：四个人格是文本模型，截屏返回的是图片路径 + 尺寸（+ 可选 OCR 文本）。
要让人格真正"看懂"屏幕像素，需接入视觉模型；当前阶段提供可靠的"操作"能力 +
尽力而为的文本化（OCR 若装了 tesseract 则附带），不吹"能看懂任意画面"。
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import DATA_DIR
from agent_base import PermissionRequest

log = logging.getLogger("computer_tools")

_CFG_PATH   = DATA_DIR / "computer_use.json"
_AUDIT_PATH = DATA_DIR / "computer_use_audit.jsonl"

VALID_MODES = ("off", "readonly", "confirm", "auto")
_READONLY_ACTIONS = {"screen_capture", "screen_info"}

# confirm 模式：单个动作等待用户确认的上限（秒）。超时默认拒绝。
_CONFIRM_TIMEOUT = 60
# 截屏保存目录
_SHOT_DIR = DATA_DIR / "screenshots"


# ── 配置读写 ─────────────────────────────────────────────
def _default_cfg() -> dict:
    return {
        "enabled": False,     # 总开关
        "mode": "off",        # off / readonly / confirm / auto
        "move_duration": 0.2, # 鼠标移动时长（秒），>0 更像人手、也更安全
    }


def load_config() -> dict:
    cfg = _default_cfg()
    if _CFG_PATH.exists():
        try:
            cfg.update(json.loads(_CFG_PATH.read_text("utf-8")) or {})
        except Exception as e:
            log.warning("读取 computer_use 配置失败: %s", e)
    if cfg.get("mode") not in VALID_MODES:
        cfg["mode"] = "off"
    if not cfg.get("enabled"):
        # 总开关关 → 强制 off，避免「enabled=false 但 mode=auto」的歧义
        cfg["mode"] = "off"
    return cfg


def save_config(patch: dict) -> dict:
    cfg = load_config()
    # load_config 在 enabled=false 时会把 mode 改成 off；保存前以磁盘原值为基准重读
    base = _default_cfg()
    if _CFG_PATH.exists():
        try:
            base.update(json.loads(_CFG_PATH.read_text("utf-8")) or {})
        except Exception:
            pass
    for k, v in (patch or {}).items():
        if k == "mode" and v not in VALID_MODES:
            continue
        if k in _default_cfg():
            base[k] = v
    if not base.get("enabled"):
        base["mode"] = "off"
    _CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CFG_PATH.write_text(json.dumps(base, ensure_ascii=False, indent=2), "utf-8")
    return load_config()


def config_public() -> dict:
    cfg = load_config()
    return {
        "enabled": cfg.get("enabled", False),
        "mode": cfg.get("mode", "off"),
        "move_duration": cfg.get("move_duration", 0.2),
        "available": _backend_available(),
    }


def _backend_available() -> bool:
    try:
        import pyautogui  # noqa: F401
        return True
    except Exception:
        return False


# ── 审计 ─────────────────────────────────────────────────
def _audit(action: str, args: dict, result: str):
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now().isoformat(),
            "action": action,
            "args": {k: (str(v)[:120]) for k, v in (args or {}).items()},
            "result": result,
        }
        with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── confirm 模式：逐动作确认桥 ───────────────────────────
class _ApprovalBridge:
    """confirm 模式下挂起控制动作，等前端逐个批准/拒绝。

    线程模型：控制动作的 dispatch 是同步调用（与既有 shell_run 一致），
    在此 Event.wait 上阻塞至多 _CONFIRM_TIMEOUT 秒。前端轮询 pending 列表，
    用户点批准/拒绝时调 resolve()。超时 → 默认拒绝（fail-safe）。
    """

    def __init__(self):
        self._pending: dict[str, dict] = {}
        self._events: dict[str, threading.Event] = {}
        self._results: dict[str, bool] = {}
        self._lock = threading.Lock()

    def request(self, action: str, summary: str) -> bool:
        aid = uuid.uuid4().hex[:12]
        ev = threading.Event()
        with self._lock:
            self._pending[aid] = {
                "id": aid, "action": action, "summary": summary,
                "ts": time.time(),
            }
            self._events[aid] = ev
        approved = False
        try:
            if ev.wait(timeout=_CONFIRM_TIMEOUT):
                approved = self._results.get(aid, False)
        finally:
            with self._lock:
                self._pending.pop(aid, None)
                self._events.pop(aid, None)
                self._results.pop(aid, None)
        return approved

    def resolve(self, aid: str, approved: bool) -> bool:
        with self._lock:
            ev = self._events.get(aid)
            if not ev:
                return False
            self._results[aid] = bool(approved)
            ev.set()
            return True

    def list_pending(self) -> list[dict]:
        now = time.time()
        with self._lock:
            return [
                {**p, "waiting": round(now - p["ts"], 1)}
                for p in self._pending.values()
            ]


bridge = _ApprovalBridge()


# ── 安全闸门 ─────────────────────────────────────────────
def _guard(action: str, args: dict):
    """统一闸门：检查总开关 / 模式 / 逐动作确认。被拦截则抛 PermissionRequest。"""
    cfg = load_config()
    enabled = cfg.get("enabled", False)
    mode = cfg.get("mode", "off")

    if not enabled or mode == "off":
        _audit(action, args, "blocked:disabled")
        raise PermissionRequest(
            api_name="桌面操作权限",
            reason="人格需要操作你的桌面（截屏/鼠标/键盘）来完成此任务，"
                   "但该能力默认关闭。请在「设置 → 桌面操作」中开启并选择授权模式。",
            related=["computer_use"],
        )

    is_control = action not in _READONLY_ACTIONS

    if mode == "readonly" and is_control:
        _audit(action, args, "blocked:readonly")
        raise PermissionRequest(
            api_name="桌面控制权限",
            reason="当前为「只读」模式，只能截屏查看，不能控制鼠标键盘。"
                   "若要让人格实际操作，请在「设置 → 桌面操作」改为「逐步确认」或「完全自动」。",
            related=["computer_use"],
        )

    if mode == "confirm" and is_control:
        summary = _describe(action, args)
        if not bridge.request(action, summary):
            _audit(action, args, "blocked:user_denied_or_timeout")
            raise PermissionRequest(
                api_name="桌面动作确认",
                reason=f"动作「{summary}」未获你确认（被拒绝或超时）。"
                       "如需继续，请在弹出的确认条上点「允许」，或切到「完全自动」模式。",
                related=["computer_use"],
            )
    # auto 模式 / readonly 下的读取动作：直接放行


def _describe(action: str, args: dict) -> str:
    a = args or {}
    if action == "mouse_click":
        btn = a.get("button", "left")
        dbl = "双击" if a.get("double") else "点击"
        return f"在 ({a.get('x')},{a.get('y')}) {btn} {dbl}"
    if action == "mouse_move":
        return f"移动鼠标到 ({a.get('x')},{a.get('y')})"
    if action == "keyboard_type":
        t = str(a.get("text", ""))
        return f"键盘输入「{t[:40]}{'…' if len(t) > 40 else ''}」"
    if action == "keyboard_hotkey":
        return f"按热键 {'+'.join(a.get('keys', []))}"
    if action == "scroll":
        return f"滚动 {a.get('amount')}"
    return action


# ── 底层执行（pyautogui / ImageGrab）─────────────────────
def _pg():
    try:
        import pyautogui
        pyautogui.FAILSAFE = True   # 鼠标甩到左上角 = 急停
        pyautogui.PAUSE = 0.0
        return pyautogui
    except Exception as e:
        raise PermissionRequest(
            api_name="桌面操作依赖",
            reason=f"未安装桌面操作依赖（pyautogui）：{e}。请运行 pip install pyautogui。",
            related=["computer_use"],
        )


def _clamp_xy(x, y) -> tuple[int, int]:
    pg = _pg()
    w, h = pg.size()
    try:
        x = int(x); y = int(y)
    except Exception:
        raise PermissionRequest(
            api_name="坐标参数",
            reason="鼠标坐标必须是整数像素值。",
        )
    x = max(0, min(w - 1, x))
    y = max(0, min(h - 1, y))
    return x, y


# ── 工具实现（被 dispatch 调用，均同步）──────────────────
def screen_info() -> dict:
    _guard("screen_info", {})
    pg = _pg()
    w, h = pg.size()
    px, py = pg.position()
    _audit("screen_info", {}, "ok")
    return {"width": w, "height": h, "mouse_x": px, "mouse_y": py}


def screen_capture(region: Optional[list] = None, ocr: bool = False) -> dict:
    """截屏并存到本机。region=[left,top,width,height] 可截局部。
    ocr=True 且装了 pytesseract 时附带识别出的文本。"""
    _guard("screen_capture", {"region": region})
    from PIL import ImageGrab
    bbox = None
    if region and len(region) == 4:
        l, t, rw, rh = region
        bbox = (int(l), int(t), int(l) + int(rw), int(t) + int(rh))
    img = ImageGrab.grab(bbox=bbox)
    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"shot_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
    fpath = _SHOT_DIR / fname
    img.save(fpath)
    out = {"path": str(fpath), "width": img.width, "height": img.height}
    if ocr:
        text = _try_ocr(img)
        out["ocr_text"] = text if text is not None else ""
        out["ocr_available"] = text is not None
    _audit("screen_capture", {"region": region, "ocr": ocr}, f"ok:{fname}")
    return out


def _try_ocr(img) -> Optional[str]:
    try:
        import pytesseract
        return pytesseract.image_to_string(img, lang="chi_sim+eng")[:4000]
    except Exception:
        return None


def mouse_move(x: int, y: int) -> dict:
    _guard("mouse_move", {"x": x, "y": y})
    pg = _pg()
    x, y = _clamp_xy(x, y)
    dur = load_config().get("move_duration", 0.2)
    pg.moveTo(x, y, duration=dur)
    _audit("mouse_move", {"x": x, "y": y}, "ok")
    return {"ok": True, "x": x, "y": y}


def mouse_click(x: Optional[int] = None, y: Optional[int] = None,
                button: str = "left", double: bool = False) -> dict:
    _guard("mouse_click", {"x": x, "y": y, "button": button, "double": double})
    pg = _pg()
    if button not in ("left", "right", "middle"):
        button = "left"
    dur = load_config().get("move_duration", 0.2)
    if x is not None and y is not None:
        x, y = _clamp_xy(x, y)
        pg.moveTo(x, y, duration=dur)
    clicks = 2 if double else 1
    pg.click(button=button, clicks=clicks, interval=0.05)
    pos = pg.position()
    _audit("mouse_click", {"x": x, "y": y, "button": button, "double": double}, "ok")
    return {"ok": True, "x": pos[0], "y": pos[1], "button": button, "double": double}


def keyboard_type(text: str) -> dict:
    _guard("keyboard_type", {"text": text})
    pg = _pg()
    # pyautogui.typewrite 对非 ASCII 支持不稳；中文走剪贴板粘贴更可靠
    if any(ord(c) > 127 for c in (text or "")):
        try:
            import pyperclip
            pyperclip.copy(text)
            pg.hotkey("ctrl", "v")
        except Exception:
            pg.typewrite(text, interval=0.02)
    else:
        pg.typewrite(text or "", interval=0.02)
    _audit("keyboard_type", {"text": text}, "ok")
    return {"ok": True, "typed_len": len(text or "")}


def keyboard_hotkey(keys: list) -> dict:
    _guard("keyboard_hotkey", {"keys": keys})
    pg = _pg()
    if not keys or not isinstance(keys, list):
        raise PermissionRequest(api_name="热键参数",
                                reason="keys 需为按键名列表，如 ['ctrl','c']。")
    pg.hotkey(*[str(k).lower() for k in keys])
    _audit("keyboard_hotkey", {"keys": keys}, "ok")
    return {"ok": True, "keys": keys}


def scroll(amount: int) -> dict:
    _guard("scroll", {"amount": amount})
    pg = _pg()
    try:
        amt = int(amount)
    except Exception:
        amt = 0
    pg.scroll(amt)
    _audit("scroll", {"amount": amount}, "ok")
    return {"ok": True, "amount": amt}


# ── 工具 schema + dispatch（供 worker 装配）──────────────
TOOL_DEFS = [
    {"type": "function", "function": {
        "name": "screen_info",
        "description": "获取屏幕分辨率和当前鼠标位置。操作前先了解坐标范围。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "screen_capture",
        "description": "截屏保存到本机，返回图片路径与尺寸。region=[left,top,width,height] 可截局部；ocr=true 且装了 tesseract 时附带文字识别。",
        "parameters": {"type": "object", "properties": {
            "region": {"type": "array", "items": {"type": "integer"},
                       "description": "[left,top,width,height]，省略则全屏"},
            "ocr": {"type": "boolean"},
        }},
    }},
    {"type": "function", "function": {
        "name": "mouse_move",
        "description": "移动鼠标到屏幕坐标 (x,y)",
        "parameters": {"type": "object", "properties": {
            "x": {"type": "integer"}, "y": {"type": "integer"},
        }, "required": ["x", "y"]},
    }},
    {"type": "function", "function": {
        "name": "mouse_click",
        "description": "在 (x,y) 点击鼠标（省略坐标则原地点击）。button: left/right/middle；double=true 为双击。",
        "parameters": {"type": "object", "properties": {
            "x": {"type": "integer"}, "y": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "double": {"type": "boolean"},
        }},
    }},
    {"type": "function", "function": {
        "name": "keyboard_type",
        "description": "用键盘输入一段文本（中文自动走剪贴板粘贴）",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
        }, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "keyboard_hotkey",
        "description": "按下组合热键，如 ['ctrl','c'] 复制、['alt','tab'] 切窗口",
        "parameters": {"type": "object", "properties": {
            "keys": {"type": "array", "items": {"type": "string"}},
        }, "required": ["keys"]},
    }},
    {"type": "function", "function": {
        "name": "scroll",
        "description": "滚动鼠标滚轮，正数上滚负数下滚",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "integer"},
        }, "required": ["amount"]},
    }},
]


def build_dispatch() -> dict:
    return {
        "screen_info":     lambda **kw: screen_info(),
        "screen_capture":  lambda **kw: screen_capture(kw.get("region"), kw.get("ocr", False)),
        "mouse_move":      lambda **kw: mouse_move(kw["x"], kw["y"]),
        "mouse_click":     lambda **kw: mouse_click(kw.get("x"), kw.get("y"),
                                                    kw.get("button", "left"), kw.get("double", False)),
        "keyboard_type":   lambda **kw: keyboard_type(kw["text"]),
        "keyboard_hotkey": lambda **kw: keyboard_hotkey(kw["keys"]),
        "scroll":          lambda **kw: scroll(kw["amount"]),
    }
