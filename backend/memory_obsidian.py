#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_obsidian.py — Obsidian Vault 记忆后端

将 Anima 记忆存储在用户已有的 Obsidian Vault 目录中。
- 读取：扫描 Memory/ 目录下的 .md 文件（和原来一样）
- 写入：追加结构化 bullet 到 Memory/USER.md
- 搜索：全文 grep（.md 文件）
- 迁移：export_snapshot 将所有条目标准化，可导入 SQLite

Obsidian 不需要安装或运行，只需要 Vault 目录存在即可。
"""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Optional

from memory_backend import (
    MemoryBackend, MemoryEntry, AGENT_MEMORY_CATEGORIES,
    INJECTION_TEMPLATES, DEFAULT_INJECTION,
)

# ── 每个 Agent 对应的 Vault 子路径 ──────────────────────────────
_AGENT_FILES: dict[str, list[str]] = {
    "xi":   ["Memory/USER.md", "Memory/preferences.md", "Daily Notes"],
    "yiyi":     ["Memory/emotional.md", "Memory/USER.md"],
    "tianyuan": ["Memory/USER.md", "Projects", "Goals"],
    "shoucang": ["Memory/knowledge_index.md", "Memory/USER.md"],
    "executor": ["Memory/USER.md"],
    "writer":   ["Memory/USER.md", "Memory/writing_style.md"],
    "reader":   ["Memory/USER.md"],
    "critic":   ["Memory/USER.md"],
}

# Anima 写入条目的格式：`- **key**：value  <!-- category ts -->`
_ENTRY_RE = re.compile(
    r'^-\s+\*\*(.+?)\*\*[：:]\s*(.+?)(?:\s*<!--\s*(\w+)\s+[\d\-T: ]+-->)?$'
)


class ObsidianMemoryBackend(MemoryBackend):
    """
    Obsidian Vault 记忆后端。
    vault_path 必须是已存在（或可创建）的目录。
    """

    def __init__(self, vault_path: str | Path):
        self.vault = Path(vault_path).expanduser().resolve()

    # ── 内部工具 ─────────────────────────────────────────────────

    def _read_path(self, relative: str, max_chars: int = 900) -> str:
        """读取 Vault 内相对路径（文件或目录取最新 .md）"""
        target = self.vault / relative
        if not target.exists():
            return ""
        try:
            if target.is_file():
                return target.read_text("utf-8", errors="replace")[:max_chars]
            if target.is_dir():
                files = sorted(
                    target.glob("*.md"),
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )
                if not files:
                    return ""
                txt = files[0].read_text("utf-8", errors="replace")[:max_chars]
                return f"[{files[0].stem}]\n{txt}"
        except Exception:
            pass
        return ""

    def _user_md(self) -> Path:
        p = self.vault / "Memory" / "USER.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def _key_to_id(key: str) -> str:
        """从 key 生成确定性 ID（可复现，delete 时可回溯）"""
        return uuid.uuid5(uuid.NAMESPACE_DNS, f"anima.obsidian.{key}").hex

    def _parse_entries(self, text: str,
                       source: str = "Memory/USER.md") -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        for line in text.splitlines():
            m = _ENTRY_RE.match(line.strip())
            if m:
                key = m.group(1).strip()
                entries.append(MemoryEntry(
                    id=self._key_to_id(key),
                    agent_id=None,
                    category=m.group(3) or "general",
                    key=key,
                    value=m.group(2).strip(),
                ))
        return entries

    # ── 核心操作 ─────────────────────────────────────────────────

    def read_for_agent(self, agent_id: str, max_chars: int = 1500) -> str:
        if not self.vault.exists():
            return ""
        paths = _AGENT_FILES.get(agent_id, ["Memory/USER.md"])
        sections: list[str] = []
        for p in paths:
            content = self._read_path(p)
            if content.strip():
                sections.append(content.strip())
        if not sections:
            return ""
        combined = "\n\n---\n\n".join(sections)
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n…[记忆已截断]"
        template = INJECTION_TEMPLATES.get(agent_id, DEFAULT_INJECTION)
        return template.format(memory=combined)

    def write(self,
              key: str,
              value: str,
              category: str = "general",
              agent_id: Optional[str] = None,
              importance: int = 3,
              remind_at: Optional[str] = None) -> str:
        """
        将结构化条目追加到 Memory/USER.md（Obsidian 可读格式）。
        如果同 key 已存在则更新该行（行内替换）。
        remind_at（M8 式④）：Obsidian 后端暂不支持到期提醒，接收但忽略。
        """
        f = self._user_md()
        ts = time.strftime("%Y-%m-%d %H:%M")
        new_line = f"- **{key}**：{value}  <!-- {category} {ts} -->"
        eid = str(uuid.uuid4())
        try:
            existing = f.read_text("utf-8", errors="replace") if f.exists() else ""
            # 检查是否已有同 key 的行
            pattern = re.compile(
                rf'^(-\s+\*\*{re.escape(key)}\*\*[：:].*)$', re.MULTILINE
            )
            if pattern.search(existing):
                updated = pattern.sub(new_line, existing, count=1)
            else:
                updated = existing.rstrip("\n") + "\n" + new_line + "\n"
            f.write_text(updated, "utf-8")
        except Exception:
            pass
        return eid

    def search(self,
               query: str,
               agent_id: Optional[str] = None,
               limit: int = 10) -> list[MemoryEntry]:
        results: list[MemoryEntry] = []
        q = query.lower()
        try:
            for md in self.vault.rglob("*.md"):
                content = md.read_text("utf-8", errors="replace")
                for line in content.splitlines():
                    if q in line.lower():
                        m = _ENTRY_RE.match(line.strip())
                        if m:
                            key = m.group(1).strip()
                            results.append(MemoryEntry(
                                id=self._key_to_id(key),
                                agent_id=None,
                                category=m.group(3) or "general",
                                key=key,
                                value=m.group(2).strip(),
                            ))
                        else:
                            note_key = f"{md.stem}:{line.strip()[:30]}"
                            results.append(MemoryEntry(
                                id=self._key_to_id(note_key),
                                agent_id=None,
                                category="note",
                                key=md.stem,
                                value=line.strip()[:200],
                            ))
                        if len(results) >= limit:
                            return results
        except Exception:
            pass
        return results

    def list_all(self,
                 agent_id: Optional[str] = None,
                 limit: int = 200) -> list[MemoryEntry]:
        f = self._user_md()
        if not f.exists():
            return []
        try:
            return self._parse_entries(
                f.read_text("utf-8", errors="replace")
            )[:limit]
        except Exception:
            return []

    def delete(self, entry_id: str) -> bool:
        """
        按 entry_id 删除 Memory/USER.md 中对应的行。
        entry_id 是 _key_to_id(key) 生成的确定性 UUID hex，
        所以先遍历所有条目找到匹配 key，再删除该行。
        """
        f = self._user_md()
        if not f.exists():
            return False
        try:
            text = f.read_text("utf-8", errors="replace")
            lines = text.splitlines()
            new_lines = []
            found = False
            for line in lines:
                m = _ENTRY_RE.match(line.strip())
                if m:
                    key = m.group(1).strip()
                    if self._key_to_id(key) == entry_id:
                        found = True
                        continue  # 跳过该行 = 删除
                new_lines.append(line)
            if found:
                f.write_text("\n".join(new_lines) + "\n", "utf-8")
            return found
        except Exception:
            return False

    # ── 项目上下文（Obsidian 专属）───────────────────────────────

    def get_project_context(self, project_name: str) -> str:
        project_dir = self.vault / "Projects" / project_name
        if not project_dir.exists():
            return ""
        try:
            readme = project_dir / "README.md"
            if readme.exists():
                content = readme.read_text("utf-8", errors="replace")
                return f"\n\n## 当前项目：{project_name}\n{content[:1000]}"
            files = sorted(
                project_dir.glob("*.md"),
                key=lambda f: f.stat().st_mtime, reverse=True,
            )
            if files:
                return f"\n\n## 当前项目：{project_name}\n" + \
                       files[0].read_text("utf-8", errors="replace")[:1000]
        except Exception:
            pass
        return ""

    def list_projects(self) -> list[dict]:
        projects_dir = self.vault / "Projects"
        if not projects_dir.exists():
            return []
        result: list[dict] = []
        for d in sorted(projects_dir.iterdir()):
            if not d.is_dir():
                continue
            readme = d / "README.md"
            desc = ""
            if readme.exists():
                try:
                    for line in readme.read_text("utf-8", errors="replace").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            desc = line[:100]
                            break
                except Exception:
                    pass
            result.append({
                "name": d.name,
                "description": desc,
                "files": len(list(d.glob("*.md"))),
            })
        return result

    def create_project(self, project_name: str, description: str = "") -> dict:
        project_dir = self.vault / "Projects" / project_name
        if project_dir.exists():
            return {"ok": False, "error": f"项目 '{project_name}' 已存在"}
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / "README.md").write_text(
                f"# {project_name}\n\n{description}\n\n## 目标\n\n待填写\n\n## 进展\n\n待填写\n",
                "utf-8",
            )
            (project_dir / "notes.md").write_text(
                f"# {project_name} — 工作笔记\n\n", "utf-8"
            )
            return {"ok": True, "name": project_name, "path": str(project_dir)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── 迁移接口 ─────────────────────────────────────────────────

    def export_snapshot(self) -> dict:
        """
        导出两部分：
        1. memories: 结构化条目列表（从 USER.md 解析）
        2. files: 所有 .md 原文（给 SQLite 以 note 形式保存）
        """
        structured = self.list_all()
        raw_files: dict[str, str] = {}
        try:
            for md in self.vault.rglob("*.md"):
                rel = str(md.relative_to(self.vault))
                content = md.read_text("utf-8", errors="replace")
                raw_files[rel] = content[:5000]  # 每文件最多 5KB
        except Exception:
            pass
        return {
            "backend":     "obsidian",
            "version":     1,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "vault_path":  str(self.vault),
            "memories":    [e.to_dict() for e in structured],
            "files":       raw_files,
        }

    def import_snapshot(self, data: dict, merge: bool = True) -> int:
        """
        将结构化 memories 写入 USER.md。
        merge=True 时跳过已有 key。
        """
        if merge:
            existing_keys = {e.key for e in self.list_all()}
        else:
            existing_keys = set()
        count = 0
        for m in data.get("memories", []):
            key = m.get("key", "")
            if not key:
                continue
            if merge and key in existing_keys:
                continue
            self.write(
                key=key,
                value=m.get("value", ""),
                category=m.get("category", "general"),
                importance=int(m.get("importance", 3)),
            )
            count += 1
        return count

    # ── 元信息 ───────────────────────────────────────────────────

    def get_backend_type(self) -> str:
        return "obsidian"

    def get_status(self) -> dict:
        ok = self.vault.exists()
        try:
            md_count = len(list(self.vault.rglob("*.md"))) if ok else 0
        except Exception:
            md_count = 0
        entries = len(self.list_all()) if ok else 0
        return {
            "type":       "obsidian",
            "label":      "Obsidian Vault",
            "ok":         ok,
            "vault_path": str(self.vault),
            "md_files":   md_count,
            "entries":    entries,
        }
