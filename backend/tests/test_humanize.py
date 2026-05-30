#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_humanize.py — AgentBase._humanize 去 AI 味清洗器单元测试 (pytest)

锁定：
  - 去掉 **加粗** / __加粗__ / ~~删除线~~ 标记，保留内文；
  - 去掉行首 # 标题井号与 - * + 项目符号，保留文字；
  - 破折号 —— → 逗号；但 3—5 这类数字区间保留；
  - 围栏代码块与行内代码原样保护（代码里的 ** * # - 不被误伤）；
  - 收尾不留连续逗号 / 逗号紧贴句末标点。

运行:
    cd E:\\Anima\\backend
    python -m pytest tests/test_humanize.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from agent_base import AgentBase  # noqa: E402

h = AgentBase._humanize


def test_strip_bold_italic_strike():
    assert h("**总体评价**：可行。") == "总体评价：可行。"
    assert h("改成 __这个__。") == "改成 这个。"
    assert h("~~删掉~~ 它。") == "删掉 它。"


def test_strip_heading_and_bullets():
    out = h("## 标题\n- 思路清晰\n- 成本可控")
    assert "#" not in out
    assert "- " not in out
    assert "思路清晰" in out and "成本可控" in out and "标题" in out


def test_emdash_to_comma_but_keep_number_range():
    assert h("没问题——我担心执行。") == "没问题，我担心执行。"
    # 数字区间里的单破折号保留，不变成逗号
    assert h("价格在 3—5 万。") == "价格在 3—5 万。"


def test_strip_numbered_list_but_keep_versions():
    out = h("1. 第一点说清楚\n2. 第二点也讲明白")
    assert "1. " not in out and "2. " not in out
    assert "第一点说清楚" in out and "第二点也讲明白" in out
    # 版本号 / 小数（无空格）不被误伤
    assert h("用的是 3.14 版本") == "用的是 3.14 版本"
    # 行首年份（4 位）不被当成编号
    assert h("2024. 这年发生了很多事") == "2024. 这年发生了很多事"


def test_code_block_protected():
    src = "看代码：```python\nx = a ** b  # 乘方\n``` 就是这样。"
    out = h(src)
    assert "a ** b" in out          # 代码块里的 ** 没被剥
    assert "```python" in out


def test_inline_code_protected():
    out = h("用 `a * b` 表示乘法，不要 **乱加粗**。")
    assert "`a * b`" in out          # 行内代码原样
    assert "乱加粗" in out and "**乱加粗**" not in out


def test_cleanup_no_double_comma():
    # —— 紧贴标点时不留「，。」「，，」
    assert "，，" not in h("一——二——三。")
    assert "，。" not in h("结束了——。")


def test_empty_and_sentinel_safe():
    assert h("") == ""
    assert h(None) is None
    # 含 \x00 的异常输入直接原样返回（占位符冲突保护）
    assert h("a\x00b") == "a\x00b"


def test_plain_text_unchanged():
    s = "能行，但有个地方得提醒你。思路清楚，成本也压得住。"
    assert h(s) == s
