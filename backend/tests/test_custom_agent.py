#!/usr/bin/env python3
"""test_custom_agent.py — D5: .anima/agents/*.md 自定义子代理"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import custom_agent as ca  # noqa: E402

_REVIEWER_MD = """\
---
name: reviewer
description: 严格的代码评审员，只挑问题不写代码
tools: [file_read, search_code, find_usages, git_diff]
model: deepseek-v4-pro
max_turns: 15
---
你是资深代码评审员。
"""


def _make_agent_dir(tmp_path, role="reviewer", content=_REVIEWER_MD):
    proj = tmp_path / "proj"
    agents_dir = proj / ".anima" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / f"{role}.md").write_text(content, encoding="utf-8")
    return str(proj)


def test_parse_agent_md(tmp_path):
    proj = _make_agent_dir(tmp_path)
    p = Path(proj) / ".anima" / "agents" / "reviewer.md"
    meta = ca._parse_agent_md(p)
    assert meta is not None
    assert meta["name"] == "reviewer"
    assert "file_read" in meta["tools"]
    assert "代码评审员" in meta["_body"]


def test_parse_agent_md_missing(tmp_path):
    assert ca._parse_agent_md(tmp_path / "nonexistent.md") is None


def test_load_custom_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_TOOL_POOL", None)
    proj = _make_agent_dir(tmp_path)
    agent = ca.load_custom_agent("reviewer", proj)
    assert agent is not None
    assert agent.name == "reviewer"
    assert agent.max_turns == 15
    assert "代码评审员" in agent.system_prompt


def test_load_custom_agent_not_found(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    assert ca.load_custom_agent("noexist", str(proj)) is None


def test_load_custom_agent_has_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_TOOL_POOL", None)
    proj = _make_agent_dir(tmp_path)
    agent = ca.load_custom_agent("reviewer", proj)
    names = [d["function"]["name"] for d in agent.tool_defs]
    assert "file_read" in names
    assert "search_code" in names


def test_list_custom_agents(tmp_path):
    proj = _make_agent_dir(tmp_path)
    agents = ca.list_custom_agents(proj)
    assert len(agents) == 1
    assert agents[0]["role"] == "reviewer"
    assert "评审" in agents[0]["description"]


def test_list_custom_agents_empty(tmp_path):
    assert ca.list_custom_agents(str(tmp_path)) == []
