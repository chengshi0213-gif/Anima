#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_hooks 用的可导入钩子目标（python:module:func 形态）。"""

RECORD: list = []


def block_hook(payload):
    return {"block": "敏感路径"}


def ok_hook(payload):
    RECORD.append(("ok", payload.get("tool")))
    return {"ok": True}


async def async_block_hook(payload):
    return {"block": "async 拦截"}


def record_post(payload):
    RECORD.append(("post", payload.get("tool"), payload.get("result")))
    return None


def boom_hook(payload):
    raise RuntimeError("钩子炸了")
