#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentLoggingMixin — 结构化日志 + 飞书通知
从 agent_base.py 抽出，独立维护。

由 AgentBase 继承；依赖 self 上的以下属性：
  self.name, self.log_dir,
  self._feishu_app_id, self._feishu_app_secret, self._feishu_chat_id
"""
import json
from datetime import datetime
from pathlib import Path

import aiohttp


class AgentLoggingMixin:
    """结构化日志落盘与飞书推送的 Mixin，供 AgentBase 继承。"""

    def _log(self, session_id: str, event: str, data: dict):
        log_file = self.log_dir / f"{self.name}-{datetime.now().strftime('%Y%m%d')}.jsonl"
        record = {"session_id": session_id, "timestamp": datetime.now().isoformat(),
                  "event": event, "agent": self.name, **data}
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    async def _notify_feishu(self, session_id, status, turns, files_changed):
        if not self._feishu_app_id or not self._feishu_app_secret:
            return
        try:
            async with aiohttp.ClientSession() as s:
                r = await s.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={"app_id": self._feishu_app_id, "app_secret": self._feishu_app_secret},
                    timeout=aiohttp.ClientTimeout(total=10))
                token = (await r.json()).get("tenant_access_token", "")
                if not token:
                    return
                emoji = "✅" if status == "completed" else "⚠️"
                text = (f"{emoji} {self.name} {status}\n"
                        f"会话: {session_id}\n轮数: {turns}\n"
                        f"文件:\n" + "\n".join(f"• {f}" for f in files_changed[:5]))
                await s.post(
                    "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"receive_id": self._feishu_chat_id, "msg_type": "text",
                          "content": json.dumps({"text": text})},
                    timeout=aiohttp.ClientTimeout(total=10))
        except Exception:
            pass
