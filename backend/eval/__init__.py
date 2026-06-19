#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval — Anima 厚 Harness 的评估脊柱（v1.3 Phase E）

核心命题：harness 改动不能盲调。先有"DeepSeek 当前自主完成率"这个数，
后面每个 harness 改动（Verify 闸门 / 定位层 / 失败记忆）都用这张表验真伪。

三件套：
  spec.py    任务集 schema（声明式 yaml：初始文件 + 提示 + 验收命令）
  runner.py  对指定模型跑全任务集，隔离临时工作区，记录 通过/轮数/耗时
  report.py  完成率报告 + 改动前后 / 模型 A vs B 对比

度量与执行解耦：runner 的 solver 可注入 → 框架本身离线可测（stub solver），
真正烧 API 额度的"跑 DeepSeek 基线"是 CLI 一步（python -m eval），留给用户触发。
"""
from .spec import EvalTask, load_task, load_tasks, TASKS_DIR  # noqa: F401
