#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_memory_loop.py — 记忆系统闭环测试
运行方式: python -X utf8 tests/test_memory_loop.py

验证三个关键路径：
  1. 写入 → 列表中可见          (write → list_all)
  2. 写入 → 搜索可发现          (write → search)
  3. 写入 → 注入文本中出现      (write → read_for_agent)

对 SQLite 和 Obsidian 两个后端均运行。
无需启动服务器，直接操作后端对象。

用法:
    cd E:\\Anima\\backend
    python tests/test_memory_loop.py

    # 只测 sqlite
    python tests/test_memory_loop.py --backend sqlite

    # 只测 obsidian
    python tests/test_memory_loop.py --backend obsidian
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
import traceback
import uuid
from pathlib import Path

# ── Windows GBK 终端兼容 ─────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.upper() not in ("UTF-8", "UTF8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── 确保 backend 目录在 sys.path ──
_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))


# ════════════════════════════════════════════════════════════════════
#  测试框架（极简）
# ════════════════════════════════════════════════════════════════════

_PASS = "✅"
_FAIL = "❌"
_results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    icon = _PASS if condition else _FAIL
    print(f"  {icon}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append((name, condition, detail))
    return condition


def section(title: str):
    print(f"\n{'━'*60}")
    print(f"  {title}")
    print(f"{'━'*60}")


def summary():
    passed = sum(1 for _, ok, _ in _results if ok)
    total  = len(_results)
    failed = [(n, d) for n, ok, d in _results if not ok]
    print(f"\n{'═'*60}")
    print(f"  结果  {passed}/{total} 通过")
    if failed:
        print("\n  失败项：")
        for name, detail in failed:
            print(f"    {_FAIL} {name}")
            if detail:
                print(f"       {detail}")
    print(f"{'═'*60}")
    return len(failed) == 0


# ════════════════════════════════════════════════════════════════════
#  SQLite 后端测试
# ════════════════════════════════════════════════════════════════════

def run_sqlite_tests():
    section("SQLite 记忆后端")
    from memory_sqlite import SQLiteMemoryBackend
    import shutil

    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_memory.db"

    backend = SQLiteMemoryBackend(str(db_path))
    tag = uuid.uuid4().hex[:8]
    KEY   = f"测试键_{tag}"
    VALUE = f"测试值_{tag}_这是一段随机内容"
    AGENT = "xi"

    # ── 1. 写入 ──────────────────────────────────────────────────
    try:
        eid = backend.write(KEY, VALUE, category="general", agent_id=AGENT, importance=4)
        check("write() 返回非空 ID", bool(eid))
    except Exception as e:
        check("write() 无异常", False, traceback.format_exc(limit=3))
        return  # 写入失败，后续测试无意义

    # ── 2. list_all ───────────────────────────────────────────────
    try:
        entries = backend.list_all(agent_id=AGENT)
        keys = [e.key for e in entries]
        check("list_all() 包含写入的 key", KEY in keys)
    except Exception as e:
        check("list_all() 无异常", False, str(e))

    # ── 3. search ────────────────────────────────────────────────
    try:
        results = backend.search(tag, agent_id=AGENT)
        found_keys = [e.key for e in results]
        check("search() 能找到写入的条目", KEY in found_keys,
              f"搜索词={tag!r}, 结果数={len(results)}, 键={found_keys[:5]}")
    except Exception as e:
        check("search() 无异常", False, str(e))

    # ── 4. read_for_agent（注入文本）─────────────────────────────
    try:
        injection = backend.read_for_agent(AGENT)
        check("read_for_agent() 返回非空字符串", bool(injection.strip()))
        check("注入文本包含 key",   KEY   in injection, f"injection前100字符={injection[:100]!r}")
        check("注入文本包含 value", VALUE in injection, f"injection前100字符={injection[:100]!r}")
    except Exception as e:
        check("read_for_agent() 无异常", False, str(e))

    # ── 5. 更新（同 key 覆盖）────────────────────────────────────
    try:
        NEW_VALUE = f"更新后的值_{tag}"
        backend.write(KEY, NEW_VALUE, category="general", agent_id=AGENT)
        entries2  = backend.list_all(agent_id=AGENT)
        matched   = [e for e in entries2 if e.key == KEY]
        check("upsert: list_all 中 key 唯一", len(matched) == 1)
        check("upsert: value 已更新", matched[0].value == NEW_VALUE if matched else False)
    except Exception as e:
        check("upsert 无异常", False, str(e))

    # ── 6. delete ────────────────────────────────────────────────
    try:
        entries_before = backend.list_all(agent_id=AGENT)
        target = next((e for e in entries_before if e.key == KEY), None)
        if target:
            ok = backend.delete(target.id)
            entries_after = backend.list_all(agent_id=AGENT)
            remaining_keys = [e.key for e in entries_after]
            check("delete() 返回 True", ok)
            check("delete() 后 list_all 中已不含该 key", KEY not in remaining_keys)
        else:
            check("delete() 前能找到条目", False, "未找到写入条目")
    except Exception as e:
        check("delete() 无异常", False, str(e))

    # 清理（删整个临时目录，避免 Windows WAL 文件锁定）
    import shutil as _shutil
    try:
        _shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
#  Obsidian 后端测试
# ════════════════════════════════════════════════════════════════════

def run_obsidian_tests():
    section("Obsidian Vault 记忆后端")
    from memory_obsidian import ObsidianMemoryBackend

    with tempfile.TemporaryDirectory() as vault_dir:
        backend = ObsidianMemoryBackend(vault_dir)
        tag = uuid.uuid4().hex[:8]
        KEY   = f"测试键_{tag}"
        VALUE = f"测试值_{tag}_Obsidian 写入内容"

        # ── 1. write ─────────────────────────────────────────────
        try:
            eid = backend.write(KEY, VALUE, category="general")
            check("write() 返回非空 ID", bool(eid))
            user_md = Path(vault_dir) / "Memory" / "USER.md"
            check("write() 创建了 Memory/USER.md", user_md.exists())
            raw = user_md.read_text("utf-8") if user_md.exists() else ""
            check("USER.md 包含写入的 key",   KEY   in raw)
            check("USER.md 包含写入的 value", VALUE in raw)
        except Exception as e:
            check("write() 无异常", False, traceback.format_exc(limit=3))
            return

        # ── 2. list_all ──────────────────────────────────────────
        try:
            entries = backend.list_all()
            keys = [e.key for e in entries]
            check("list_all() 包含写入的 key", KEY in keys,
                  f"keys={keys}")
        except Exception as e:
            check("list_all() 无异常", False, str(e))

        # ── 3. search ────────────────────────────────────────────
        try:
            results = backend.search(tag)
            check("search() 能找到写入的条目",
                  any(tag in e.key or tag in e.value for e in results),
                  f"搜索词={tag!r}, 结果数={len(results)}")
        except Exception as e:
            check("search() 无异常", False, str(e))

        # ── 4. read_for_agent ────────────────────────────────────
        try:
            injection = backend.read_for_agent("xi")
            check("read_for_agent() 返回非空字符串", bool(injection.strip()))
            check("注入文本包含写入内容", KEY in injection or VALUE in injection,
                  f"injection前200字符={injection[:200]!r}")
        except Exception as e:
            check("read_for_agent() 无异常", False, str(e))

        # ── 5. upsert（同 key 替换）──────────────────────────────
        try:
            NEW_VALUE = f"更新后的值_{tag}"
            backend.write(KEY, NEW_VALUE, category="general")
            raw2  = (Path(vault_dir) / "Memory" / "USER.md").read_text("utf-8")
            count = raw2.count(f"**{KEY}**")
            check("upsert: USER.md 中 key 行唯一", count == 1,
                  f"出现次数={count}")
            check("upsert: USER.md 包含新 value", NEW_VALUE in raw2)
        except Exception as e:
            check("upsert 无异常", False, str(e))

        # ── 6. export_snapshot ───────────────────────────────────
        try:
            snap = backend.export_snapshot()
            check("export_snapshot() 返回 dict", isinstance(snap, dict))
            check("snapshot.backend == 'obsidian'", snap.get("backend") == "obsidian")
            check("snapshot.memories 非空", len(snap.get("memories", [])) > 0)
        except Exception as e:
            check("export_snapshot() 无异常", False, str(e))


# ════════════════════════════════════════════════════════════════════
#  跨后端：memory_injector 门面层测试
# ════════════════════════════════════════════════════════════════════

def run_injector_tests():
    section("memory_injector 门面层（SQLite 模式）")
    from memory_injector import (
        write_memory, get_memory_injection, search_memory,
        get_backend, list_memory,
    )

    import shutil
    tmp_dir = tempfile.mkdtemp()
    db_path = str(Path(tmp_dir) / "injector_test.db")

    # 临时切换到测试 DB
    import memory_injector as _mi
    import memory_sqlite as _ms
    _orig_backend = _mi._backend
    _mi._backend  = _ms.SQLiteMemoryBackend(db_path)

    tag   = uuid.uuid4().hex[:8]
    KEY   = f"injector_{tag}"
    VALUE = f"门面层测试_{tag}"

    try:
        # write_memory
        try:
            eid = write_memory(KEY, VALUE, category="preference", agent_id="xi", importance=3)
            check("write_memory() 返回非空 ID", bool(eid))
        except Exception as e:
            check("write_memory() 无异常", False, str(e))

        # get_memory_injection
        try:
            injection = get_memory_injection("xi")
            check("get_memory_injection() 非空", bool(injection.strip()))
            check("get_memory_injection() 包含写入内容", KEY in injection or VALUE in injection,
                  f"injection前200字符={injection[:200]!r}")
        except Exception as e:
            check("get_memory_injection() 无异常", False, str(e))

        # search_memory
        try:
            results = search_memory(tag, agent_id="xi")
            check("search_memory() 找到条目", len(results) > 0,
                  f"搜索词={tag!r}, 结果数={len(results)}")
        except Exception as e:
            check("search_memory() 无异常", False, str(e))

        # get_backend status check
        try:
            backend = get_backend()
            status = backend.get_status()
            check("get_backend().get_status() 返回 dict", isinstance(status, dict))
            check("status.ok == True", status.get("ok") is True,
                  f"status={status}")
        except Exception as e:
            check("backend.get_status() 无异常", False, str(e))

    finally:
        _mi._backend = _orig_backend
        import shutil as _shutil
        try:
            _shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
#  main
# ════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="记忆系统闭环测试")
    parser.add_argument("--backend", choices=["sqlite", "obsidian", "injector", "all"],
                        default="all", help="指定要测试的后端（默认 all）")
    args = parser.parse_args()

    print("\n🧠  Anima 记忆系统闭环测试")
    print(f"    Python {sys.version.split()[0]}  |  后端: {args.backend}\n")

    try:
        if args.backend in ("sqlite", "all"):
            run_sqlite_tests()
        if args.backend in ("obsidian", "all"):
            run_obsidian_tests()
        if args.backend in ("injector", "all"):
            run_injector_tests()
    except ImportError as e:
        print(f"\n❌ 导入失败: {e}")
        print("   请确保在 backend/ 目录下运行，且已安装所有依赖（pip install -r requirements.txt）")
        sys.exit(2)

    ok = summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
