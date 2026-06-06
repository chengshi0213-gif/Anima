#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件访问护栏 — Anima
------------------------------------------------------------
设计取向（重要）：
  Anima 是对标 Codex / Claude Code 的编程 agent，本就需要广泛的文件访问，
  纯白名单会废掉核心能力。因此这里用"护栏式"安全策略：
    · 默认放行正常开发路径
    · 硬性拦截凭证/密钥文件（防 prompt 注入窃取）
    · 硬性拦截系统关键目录的写入（防破坏系统）

防的是：被注入的指令去读 ~/.ssh/id_rsa、~/.anima/.secret.key、
        ~/.aws/credentials，或往系统启动目录写文件。
不防的是：能完整控制本机的攻击者（那不在本工具的威胁模型内）。
"""
import os
from pathlib import Path

# 凭证文件名（读写都禁）
_SECRET_NAMES = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",   # SSH 私钥
    ".secret.key",                                   # Anima 本地加密密钥
    "ntuser.dat",
}
# 凭证目录名（路径中任一段命中即禁）
_SECRET_DIR_PARTS = {".ssh", ".aws", ".gnupg"}


def _home() -> Path:
    return Path.home()


def _norm(p: Path) -> str:
    try:
        rp = p.resolve()
    except Exception:
        rp = p
    s = str(rp)
    if os.name == "nt":
        s = s.lower()
    return s


def _is_under(norm_child: str, parent: Path) -> bool:
    try:
        pp = _norm(parent)
        return (norm_child == pp
                or norm_child.startswith(pp + os.sep)
                or norm_child.startswith(pp + "/"))
    except Exception:
        return False


def _system_write_denied_roots() -> list:
    roots = []
    if os.name == "nt":
        for env in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            v = os.environ.get(env)
            if v:
                roots.append(Path(v))
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.append(Path(appdata) / "Microsoft" / "Windows"
                         / "Start Menu" / "Programs" / "Startup")
    else:
        roots += [Path("/etc"), Path("/usr"), Path("/bin"), Path("/sbin"),
                  Path("/boot"), Path("/sys")]
        # macOS 系统目录
        roots += [Path("/System"), Path("/Library")]
    return roots


def check_path(path: str, write: bool = False) -> tuple:
    """
    返回 (allowed: bool, reason: str)。
    allowed=False 时 reason 给出拒绝原因（可直接回给 agent / 用户）。
    """
    if not path or not str(path).strip():
        return False, "空路径"
    try:
        p = Path(path).expanduser()
    except Exception:
        return False, "非法路径"

    norm = _norm(p)
    name = p.name.lower()

    # 1) 凭证文件名
    if name in _SECRET_NAMES or name.startswith("id_rsa"):
        return False, f"安全策略：禁止访问凭证文件「{p.name}」"

    # 2) 凭证目录（.ssh/.aws/.gnupg 等出现在路径任一段）
    parts_lower = {part.lower() for part in p.parts}
    hit = parts_lower & _SECRET_DIR_PARTS
    if hit:
        return False, f"安全策略：禁止访问凭证目录「{', '.join(hit)}」"

    # 3) Anima 自身的密钥与配置（含 API Key 密文）
    blocked = {
        _norm(_home() / ".anima" / ".secret.key"),
        _norm(_home() / ".anima" / "config.yaml"),
    }
    if norm in blocked:
        return False, "安全策略：禁止访问 Anima 的凭证/配置文件"

    # 4) 写入系统目录
    if write:
        for root in _system_write_denied_roots():
            if _is_under(norm, root):
                return False, f"安全策略：禁止写入系统目录「{root}」"

    # 5) 用户自定义黑名单（config.yaml: security.denied_paths: [...]）
    try:
        import config as _cfg
        for extra in (_cfg._get("security.denied_paths", []) or []):
            try:
                if _is_under(norm, Path(extra).expanduser()):
                    return False, "安全策略：该路径在你的自定义黑名单中"
            except Exception:
                pass
    except Exception:
        pass

    return True, ""
