#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage 统计 — 从 JSONL 日志聚合 API 数据"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

class UsageTracker:
    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)

    def get_daily_stats(self, days: int = 7) -> dict:
        today = datetime.now().date()
        daily = defaultdict(lambda: {"tokens": 0, "sessions": 0, "cost": 0.0})
        for i in range(days):
            date = today - timedelta(days=i)
            for log_file in self.log_dir.glob(f"*-{date.strftime('%Y%m%d')}.jsonl"):
                try:
                    for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
                        if not line: continue
                        entry = json.loads(line)
                        tokens = (entry.get("input_tokens", 0) or 0) + (entry.get("output_tokens", 0) or 0)
                        if tokens:
                            daily[date.isoformat()]["tokens"] += tokens
                        if entry.get("event") == "session_start":
                            daily[date.isoformat()]["sessions"] += 1
                except Exception:
                    pass
        for d in daily.values():
            d["cost"] = round(d["tokens"] / 1_000_000 * 1.0, 2)
        return {
            "daily": [{"date": k, **v} for k, v in sorted(daily.items())],
            "total_tokens": sum(d["tokens"] for d in daily.values()),
            "total_cost": round(sum(d["cost"] for d in daily.values()), 2),
            "total_sessions": sum(d["sessions"] for d in daily.values()),
        }

    def get_per_agent_stats(self, days: int = 7) -> dict:
        agent_stats = defaultdict(lambda: {"tokens": 0, "sessions": 0})
        today = datetime.now().date()
        for i in range(days):
            date = today - timedelta(days=i)
            for log_file in self.log_dir.glob(f"*-{date.strftime('%Y%m%d')}.jsonl"):
                agent_name = log_file.stem.rsplit("-", 1)[0]
                try:
                    for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
                        if not line: continue
                        entry = json.loads(line)
                        tokens = (entry.get("input_tokens", 0) or 0) + (entry.get("output_tokens", 0) or 0)
                        if tokens:
                            agent_stats[agent_name]["tokens"] += tokens
                        if entry.get("event") == "session_start":
                            agent_stats[agent_name]["sessions"] += 1
                except Exception:
                    pass
        return {"agents": [
            {"name": k, "tokens": v["tokens"], "sessions": v["sessions"],
             "cost": round(v["tokens"] / 1_000_000 * 1.0, 2)}
            for k, v in sorted(agent_stats.items())
        ]}

    def get_monthly_projection(self) -> dict:
        now = datetime.now()
        days_elapsed = now.day
        stats = self.get_daily_stats(days=days_elapsed)
        if days_elapsed == 0:
            return {"projected_cost": 0, "daily_avg": 0}
        daily_avg = stats["total_cost"] / days_elapsed
        return {
            "days_elapsed": days_elapsed,
            "daily_avg": round(daily_avg, 2),
            "projected_cost": round(daily_avg * 30, 2),
            "total_so_far": stats["total_cost"],
        }
