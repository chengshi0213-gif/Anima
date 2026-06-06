#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""崩溃上报与诊断测试 — crash_reporter"""
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import crash_reporter as cr


def test_scrub_removes_keys():
    s = cr._scrub("key sk-ant-api03-SECRET123456 and tok "
                  "abcdef1234567890abcdef1234567890XX")
    assert "sk-ant" not in s
    assert "SECRET123456" not in s
    assert "[REDACTED]" in s


def test_dump_exception_writes_scrubbed_file():
    try:
        raise ValueError("boom sk-test-LEAK1234567890abcdefXX")
    except Exception as e:
        path = cr.dump_exception(type(e), e, e.__traceback__, context="unit-test")
    assert path and os.path.exists(path)
    txt = Path(path).read_text(encoding="utf-8")
    assert "sk-test-LEAK" not in txt
    assert "unit-test" in txt


def test_export_diagnostics_zip_scrubbed():
    fe = [{"msg": "js err", "key": "sk-front-LEAK1234567890abcXX"}]
    r = cr.export_diagnostics(frontend_errors=fe)
    assert r.get("ok") and os.path.exists(r["path"])
    with zipfile.ZipFile(r["path"]) as z:
        names = z.namelist()
        assert "system_info.json" in names
        assert "frontend_errors.json" in names
        fe_txt = z.read("frontend_errors.json").decode("utf-8")
        assert "sk-front-LEAK" not in fe_txt


def test_list_crashes_returns_list():
    assert isinstance(cr.list_crashes(), list)
