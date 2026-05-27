#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workflow 模板管理器
保存/加载/列出常用提示词模板
"""
import json, os
from pathlib import Path
from datetime import datetime


class WorkflowManager:
    """管理用户保存的 Workflow 模板"""

    def __init__(self, store_dir: Path):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, prompt: str, agent: str = "xi") -> dict:
        """保存模板"""
        # 清理文件名
        safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip()[:50]
        if not safe_name:
            return {"error": "无效的模板名称"}
        path = self.store_dir / f"{safe_name}.json"
        data = {
            "name": name,
            "agent": agent,
            "prompt": prompt,
            "created": datetime.now().isoformat(),
            "used_count": 0,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"saved": True, "name": name, "path": str(path)}

    def load(self, name: str) -> dict | None:
        """加载模板"""
        path = self.store_dir / f"{name}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        # 增加使用计数
        data["used_count"] = data.get("used_count", 0) + 1
        data["last_used"] = datetime.now().isoformat()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def list_all(self, agent: str | None = None) -> list[dict]:
        """列出所有模板"""
        templates = []
        for f in sorted(self.store_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if agent and data.get("agent") != agent:
                    continue
                data["id"] = f.stem
                templates.append(data)
            except Exception:
                pass
        return templates

    def delete(self, name: str) -> bool:
        """删除模板"""
        path = self.store_dir / f"{name}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # ── 完整工作流（多步骤）──────────────────────────
    def save_workflow(self, wf_id: str | None, name: str, steps: list) -> dict:
        """保存完整工作流定义（多步骤）"""
        import uuid
        wf_id = wf_id or str(uuid.uuid4())[:8]
        safe  = "wf_" + wf_id
        path  = self.store_dir / f"{safe}.json"
        data  = {
            "id":      wf_id,
            "name":    name,
            "steps":   steps,
            "created": datetime.now().isoformat(),
            "type":    "workflow",
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"id": wf_id, "name": name, "saved": True}

    def list_all(self, agent: str | None = None) -> list[dict]:
        """列出所有模板和工作流"""
        templates = []
        for f in sorted(self.store_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if agent and data.get("agent") != agent and data.get("type") == "template":
                    continue
                data["id"] = f.stem.removeprefix("wf_") if f.stem.startswith("wf_") else f.stem
                templates.append(data)
            except Exception:
                pass
        return templates

    def load_workflow(self, wf_id: str) -> dict | None:
        path = self.store_dir / f"wf_{wf_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def delete_workflow(self, wf_id: str) -> bool:
        path = self.store_dir / f"wf_{wf_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False
