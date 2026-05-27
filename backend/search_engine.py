#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FTS5 全文搜索引擎 — Anima 桌面端跨会话搜索
"""
import sqlite3, json
from pathlib import Path
from datetime import datetime

class SearchEngine:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, agent TEXT, timestamp TEXT, summary TEXT)""")
        self.conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            session_id, role, content, tokenize='unicode61')""")
        self.conn.commit()

    def index_session(self, session_id: str, agent: str, messages: list):
        self.conn.execute(
            "INSERT OR REPLACE INTO sessions(session_id,agent,timestamp,summary) VALUES(?,?,?,?)",
            (session_id, agent, datetime.now().isoformat(),
             messages[-1].get("content","")[:500] if messages else ""))
        for m in messages:
            role = m.get("role","")
            content = m.get("content","")
            if isinstance(content, str) and content.strip():
                self.conn.execute(
                    "INSERT INTO messages_fts(session_id,role,content) VALUES(?,?,?)",
                    (session_id, role, content[:2000]))
        self.conn.commit()

    def search(self, query: str, agent: str|None=None, limit: int=20) -> list:
        where = f"AND messages_fts.session_id IN (SELECT session_id FROM sessions WHERE agent='{agent}')" if agent else ""
        rows = self.conn.execute(f"""
            SELECT messages_fts.session_id, role, snippet(messages_fts,1,'<mark>','</mark>','…',40),
                   sessions.timestamp, sessions.agent
            FROM messages_fts JOIN sessions ON messages_fts.session_id=sessions.session_id
            WHERE messages_fts MATCH ? {where} ORDER BY rank LIMIT ?
        """, (query, limit)).fetchall()
        return [{"session_id":r[0],"role":r[1],"snippet":r[2],"timestamp":r[3],"agent":r[4]} for r in rows]

    def list_sessions(self, agent: str|None=None, limit: int=30) -> list:
        """列出最近会话（按时间倒序）"""
        if agent:
            rows = self.conn.execute(
                "SELECT session_id,agent,timestamp,summary FROM sessions WHERE agent=? ORDER BY timestamp DESC LIMIT ?",
                (agent, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT session_id,agent,timestamp,summary FROM sessions ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [{"session_id":r[0],"agent":r[1],"timestamp":r[2],"summary":r[3]} for r in rows]

    def get_session_messages(self, session_id: str) -> list:
        """获取会话的所有消息"""
        rows = self.conn.execute(
            "SELECT role,content FROM messages_fts WHERE session_id=?",
            (session_id,)
        ).fetchall()
        return [{"role":r[0],"content":r[1]} for r in rows]

    def close(self):
        self.conn.close()
