#!/usr/bin/env python3
"""custom_commands.py — D7: .anima/commands/*.md 自定义快捷命令。

文件名 = 命令名（如 fix-typos.md → /fix-typos）。
正文 = 任务模板，$ARGUMENTS 占位符替换为用户参数。
可选 YAML frontmatter（description 供索引展示）。
"""
from __future__ import annotations

from pathlib import Path


def _parse_command_md(path: Path) -> dict | None:
    try:
        text = path.read_text("utf-8")
    except Exception:
        return None
    name = path.stem
    body = text
    description = ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                import yaml
                meta = yaml.safe_load(parts[1]) or {}
                description = meta.get("description", "")
            except Exception:
                pass
            body = parts[2].strip()
    return {"name": name, "description": description or name, "body": body}


def list_commands(project_root: str) -> list[dict]:
    d = Path(project_root) / ".anima" / "commands"
    if not d.is_dir():
        return []
    result = []
    for md in sorted(d.glob("*.md")):
        meta = _parse_command_md(md)
        if meta:
            result.append({"name": meta["name"], "description": meta["description"]})
    return result


def load_command(name: str, project_root: str, arguments: str = "") -> str | None:
    p = Path(project_root) / ".anima" / "commands" / f"{name}.md"
    meta = _parse_command_md(p)
    if meta is None:
        return None
    body = meta["body"]
    if "$ARGUMENTS" in body:
        body = body.replace("$ARGUMENTS", arguments)
    return body
