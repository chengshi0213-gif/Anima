#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FTS5 全文搜索引擎 — Anima 桌面端跨会话搜索
"""
import sqlite3, json, threading
from pathlib import Path
from datetime import datetime

class SearchEngine:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        # 单连接被多个 WorkerServer 共享，且可能被 asyncio.to_thread 调用，
        # 用锁串行化所有读写，避免 "database is locked" / 游标竞争。
        self._lock = threading.Lock()
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, agent TEXT, timestamp TEXT, summary TEXT)""")
        self.conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            session_id, role, content, tokenize='unicode61')""")
        self.conn.commit()

    def index_session(self, session_id: str, agent: str, messages: list):
        with self._lock:
            # 重新索引前先清掉旧记录，避免同一会话多轮重复堆积、FTS 表无界增长
            self.conn.execute("DELETE FROM messages_fts WHERE session_id=?", (session_id,))
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
        # 参数化绑定 agent，杜绝 SQL 注入；JOIN 已带出 sessions，直接按 sessions.agent 过滤
        if agent:
            sql = """
                SELECT messages_fts.session_id, role, snippet(messages_fts,1,'<mark>','</mark>','…',40),
                       sessions.timestamp, sessions.agent
                FROM messages_fts JOIN sessions ON messages_fts.session_id=sessions.session_id
                WHERE messages_fts MATCH ? AND sessions.agent = ? ORDER BY rank LIMIT ?
            """
            params = (query, agent, limit)
        else:
            sql = """
                SELECT messages_fts.session_id, role, snippet(messages_fts,1,'<mark>','</mark>','…',40),
                       sessions.timestamp, sessions.agent
                FROM messages_fts JOIN sessions ON messages_fts.session_id=sessions.session_id
                WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?
            """
            params = (query, limit)
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [{"session_id":r[0],"role":r[1],"snippet":r[2],"timestamp":r[3],"agent":r[4]} for r in rows]

    def list_sessions(self, agent: str|None=None, limit: int=30) -> list:
        """列出最近会话（按时间倒序）"""
        with self._lock:
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
        with self._lock:
            rows = self.conn.execute(
                "SELECT role,content FROM messages_fts WHERE session_id=?",
                (session_id,)
            ).fetchall()
        return [{"role":r[0],"content":r[1]} for r in rows]

    def delete_session(self, session_id: str) -> None:
        """删除某条历史会话"""
        with self._lock:
            self.conn.execute("DELETE FROM messages_fts WHERE session_id=?", (session_id,))
            self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()
