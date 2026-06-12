#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_native_tools.py — v1.2.1 原生工具层单元测试 (pytest)

T1: glob_files（按文件名模式找文件）+ map_project（项目全景树）。
后续 T2-T7（long_run/install_pkg/read_image/read_pdf/http_request/git）陆续追加到本文件。

运行:
    cd E:\\AI\\workspace\\Anima\\backend
    python -m pytest tests/test_native_tools.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import xi_worker as xw  # noqa: E402
import capabilities  # noqa: E402


@pytest.fixture
def sample_tree(tmp_path):
    """造一个含噪声目录的小项目树。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "src" / "util.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test(): pass", encoding="utf-8")
    (tmp_path / "README.md").write_text("# proj", encoding="utf-8")
    # 噪声：应被 map_project 跳过
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("nope", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    return tmp_path


# ── T1: glob_files ────────────────────────────────────────────────────────────

def test_glob_files_recursive(sample_tree):
    r = xw._glob_files("**/*.py", str(sample_tree))
    assert "error" not in r
    names = {Path(f).name for f in r["files"]}
    assert names == {"app.py", "util.py", "test_app.py"}
    assert r["count"] == 3


def test_glob_files_pattern_filters(sample_tree):
    r = xw._glob_files("**/test_*.py", str(sample_tree))
    assert {Path(f).name for f in r["files"]} == {"test_app.py"}


def test_glob_files_sorted_by_mtime_desc(sample_tree):
    # 显式设置 mtime：util.py 最新，app.py 最旧
    os.utime(sample_tree / "src" / "app.py", (1000, 1000))
    os.utime(sample_tree / "tests" / "test_app.py", (2000, 2000))
    os.utime(sample_tree / "src" / "util.py", (3000, 3000))
    r = xw._glob_files("**/*.py", str(sample_tree))
    order = [Path(f).name for f in r["files"]]
    assert order == ["util.py", "test_app.py", "app.py"]


def test_glob_files_limit_and_truncated(sample_tree):
    r = xw._glob_files("**/*.py", str(sample_tree), limit=2)
    assert r["count"] == 2
    assert r["truncated"] is True


def test_glob_files_missing_path():
    r = xw._glob_files("*.py", "/no/such/dir/xyz")
    assert "error" in r


# ── T1: map_project ───────────────────────────────────────────────────────────

def test_map_project_skips_noise(sample_tree):
    r = xw._map_project(str(sample_tree))
    assert "error" not in r
    tree = r["tree"]
    assert "app.py" in tree and "README.md" in tree
    # 噪声目录及其内容不出现
    assert "node_modules" not in tree
    assert "junk.js" not in tree
    assert ".git" not in tree


def test_map_project_counts(sample_tree):
    r = xw._map_project(str(sample_tree))
    # 目录 src + tests（node_modules/.git 被跳过）
    assert r["dirs"] == 2
    # 文件 app.py/util.py/test_app.py/README.md
    assert r["files"] == 4


def test_map_project_respects_depth(sample_tree):
    # max_depth=0 → 只列根层条目，不进入子目录内容
    r = xw._map_project(str(sample_tree), max_depth=0)
    tree = r["tree"]
    assert "src/" in tree
    assert "app.py" not in tree   # 深度 1 的内容不展开


def test_map_project_missing_root():
    r = xw._map_project("/no/such/root/xyz")
    assert "error" in r


# ── 注册到 execution capability ───────────────────────────────────────────────

def test_execution_cap_registers_t1_tools():
    cap = capabilities.build(["execution"], agent_id="xi")
    names = {d["function"]["name"] for d in cap["tool_defs"]}
    assert "glob_files" in names
    assert "map_project" in names
    assert "glob_files" in cap["dispatch"]
    assert "map_project" in cap["dispatch"]


def test_execution_cap_dispatch_runs(sample_tree):
    cap = capabilities.build(["execution"], agent_id="xi")
    out = cap["dispatch"]["glob_files"](pattern="**/*.md", path=str(sample_tree))
    assert {Path(f).name for f in out["files"]} == {"README.md"}
    out2 = cap["dispatch"]["map_project"](root=str(sample_tree))
    assert "node_modules" not in out2["tree"]


# ── T6: http_request（SSRF 安全闸门）──────────────────────────────────────────

import native_tools as nt  # noqa: E402


@pytest.mark.parametrize("host", [
    "localhost", "127.0.0.1", "10.0.0.5", "192.168.1.1",
    "172.16.0.1", "169.254.1.1", "0.0.0.0",
])
def test_host_is_internal_blocks_private(host):
    internal, reason = nt._host_is_internal(host)
    assert internal is True
    assert reason


def test_host_is_internal_allows_public_ip():
    internal, _ = nt._host_is_internal("8.8.8.8")
    assert internal is False


def test_http_request_blocks_internal_url():
    r = nt._http_request("GET", "http://127.0.0.1:9100/health")
    assert "error" in r
    assert "SSRF" in r["error"] or "拦截" in r["error"]


def test_http_request_blocks_localhost():
    r = nt._http_request("GET", "http://localhost/admin")
    assert "error" in r and "status" not in r


def test_http_request_rejects_non_http_scheme():
    assert "error" in nt._http_request("GET", "file:///etc/passwd")
    assert "error" in nt._http_request("GET", "ftp://8.8.8.8/x")


def test_http_request_rejects_bad_method():
    assert "error" in nt._http_request("FETCH", "http://8.8.8.8/x")


def test_http_request_success_path(monkeypatch):
    """公网 IP（8.8.8.8 字面量，离线即可判定非内网）走通；monkeypatch opener 避免真连。"""
    class _FakeResp:
        status = 200
        headers = {"Content-Type": "application/json"}
        def read(self, n=-1):
            return b'{"ok": true}'
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class _FakeOpener:
        def open(self, req, timeout=None):
            # 断言 JSON body 已被正确序列化 + 自动补 Content-Type
            assert req.get_header("Content-type") == "application/json"
            return _FakeResp()

    monkeypatch.setattr(nt, "_OPENER", _FakeOpener())
    r = nt._http_request("POST", "http://8.8.8.8/api", body={"q": "你好"})
    assert r["status"] == 200
    assert r["body"] == '{"ok": true}'
    assert r["truncated"] is False


def test_execution_cap_registers_http_request():
    cap = capabilities.build(["execution"], agent_id="xi")
    names = {d["function"]["name"] for d in cap["tool_defs"]}
    assert "http_request" in names
    assert "http_request" in cap["dispatch"]
    # dispatch 默认 method=GET，内网 URL 应被拦
    out = cap["dispatch"]["http_request"](url="http://10.0.0.1/x")
    assert "error" in out


# ── T7: git_tools 六件套 ─────────────────────────────────────────────────────

import subprocess  # noqa: E402
import git_tools as gt  # noqa: E402


@pytest.fixture
def git_repo(tmp_path):
    """在 tmp_path 创建一个干净的 git 仓库并提交一个文件。"""
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=str(tmp_path), capture_output=True)
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"],
                   cwd=str(tmp_path), capture_output=True)
    return tmp_path


def test_git_status_clean(git_repo):
    r = gt._git_status(str(git_repo))
    assert "error" not in r
    assert r["clean"] is True
    assert r["branch"]


def test_git_status_dirty(git_repo):
    (git_repo / "new.txt").write_text("x", encoding="utf-8")
    r = gt._git_status(str(git_repo))
    assert r["clean"] is False
    assert any(c["file"] == "new.txt" for c in r["changes"])


def test_git_status_not_a_repo(tmp_path):
    r = gt._git_status(str(tmp_path))
    assert "error" in r


def test_git_diff_shows_changes(git_repo):
    (git_repo / "hello.txt").write_text("hello world", encoding="utf-8")
    r = gt._git_diff(str(git_repo))
    assert "error" not in r
    assert "hello world" in r["diff"]


def test_git_diff_staged(git_repo):
    (git_repo / "hello.txt").write_text("staged change", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(git_repo), capture_output=True)
    r = gt._git_diff(str(git_repo), staged=True)
    assert "staged change" in r["diff"]


def test_git_commit_success(git_repo):
    (git_repo / "feat.py").write_text("print(1)", encoding="utf-8")
    r = gt._git_commit(str(git_repo), "add feat")
    assert r["committed"] is True
    assert r["hash"]
    assert r["message"] == "add feat"


def test_git_commit_empty_message(git_repo):
    r = gt._git_commit(str(git_repo), "")
    assert "error" in r
    assert "空" in r["error"]


def test_git_commit_excludes_sensitive(git_repo):
    (git_repo / ".env").write_text("SECRET=abc", encoding="utf-8")
    (git_repo / "ok.txt").write_text("safe", encoding="utf-8")
    r = gt._git_commit(str(git_repo), "mixed commit")
    assert r["committed"] is True
    assert ".env" in r["excluded_sensitive"]


def test_git_commit_only_sensitive(git_repo):
    (git_repo / ".env").write_text("SECRET=abc", encoding="utf-8")
    r = gt._git_commit(str(git_repo), "only sensitive")
    assert r["committed"] is False
    assert "敏感" in r.get("reason", "")


def test_git_log(git_repo):
    r = gt._git_log(str(git_repo))
    assert "error" not in r
    assert r["count"] >= 1
    assert "init" in r["commits"][0]


def test_git_branch(git_repo):
    r = gt._git_branch(str(git_repo))
    assert "error" not in r
    assert r["current"] in r["branches"]


def test_git_create_branch(git_repo):
    r = gt._git_create_branch(str(git_repo), "feat/test-branch")
    assert r["created"] is True
    assert r["branch"] == "feat/test-branch"
    cur = gt._git_branch(str(git_repo))
    assert cur["current"] == "feat/test-branch"


def test_git_create_branch_invalid_name(git_repo):
    r = gt._git_create_branch(str(git_repo), "")
    assert "error" in r
    r2 = gt._git_create_branch(str(git_repo), "bad name with spaces")
    assert "error" in r2


def test_git_log_limit(git_repo):
    for i in range(5):
        (git_repo / f"f{i}.txt").write_text(str(i), encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(git_repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", f"commit {i}"],
                       cwd=str(git_repo), capture_output=True)
    r = gt._git_log(str(git_repo), limit=3)
    assert r["count"] == 3


# ── T5: read_pdf ─────────────────────────────────────────────────────────────


@pytest.fixture
def small_pdf(tmp_path):
    """用 pypdf 生成一个 3 页的简单 PDF。"""
    from pypdf import PdfWriter
    from pypdf.generic import AnnotationBuilder
    import io
    writer = PdfWriter()
    for i in range(3):
        from reportlab.pdfgen import canvas as rl_canvas
        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf)
        c.drawString(100, 700, f"Page {i+1} content hello")
        c.showPage()
        c.save()
        buf.seek(0)
        from pypdf import PdfReader as _PR
        writer.add_page(_PR(buf).pages[0])
    pdf_path = tmp_path / "test.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


@pytest.fixture
def small_pdf_simple(tmp_path):
    """用 fpdf2 或纯手工构造一个极小 PDF（不依赖 reportlab）。"""
    try:
        from fpdf import FPDF
        pdf = FPDF()
        for i in range(3):
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            pdf.cell(200, 10, text=f"Page {i+1} content hello")
        pdf_path = tmp_path / "test.pdf"
        pdf.output(str(pdf_path))
        return pdf_path
    except ImportError:
        pass
    # 最后手段：用 pypdf 创建空白页（无文本，但能测路径/页数逻辑）
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=612, height=792)
    pdf_path = tmp_path / "blank.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


def test_read_pdf_missing_file():
    r = nt._read_pdf("/no/such/file.pdf")
    assert "error" in r


def test_read_pdf_not_pdf(tmp_path):
    f = tmp_path / "readme.txt"
    f.write_text("hello", encoding="utf-8")
    r = nt._read_pdf(str(f))
    assert "error" in r
    assert "不是 PDF" in r["error"]


def test_read_pdf_blank_pages(tmp_path):
    """空白页 PDF — 两个 extractor 都拿不到文本，应报错不是静默返回空。"""
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(2):
        w.add_blank_page(612, 792)
    p = tmp_path / "blank.pdf"
    with open(p, "wb") as f:
        w.write(f)
    r = nt._read_pdf(str(p))
    assert "error" in r or (r.get("text", "").strip() == "")


def test_read_pdf_large_no_range(tmp_path, monkeypatch):
    """超 100 页的 PDF 不给页范围应报错。"""
    monkeypatch.setattr(nt, "_pdf_page_count", lambda path: 150)
    p = tmp_path / "big.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    r = nt._read_pdf(str(p))
    assert "error" in r
    assert "start_page" in r["error"]


def test_read_pdf_execution_cap_registration():
    cap = capabilities.build(["execution"], agent_id="xi")
    names = {d["function"]["name"] for d in cap["tool_defs"]}
    assert "read_pdf" in names
    assert "read_pdf" in cap["dispatch"]


# ── T4: read_image ───────────────────────────────────────────────────────────


def test_read_image_missing_file():
    r = nt._read_image("/no/such/image.png")
    assert "error" in r


def test_read_image_wrong_extension(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("a,b,c", encoding="utf-8")
    r = nt._read_image(str(f))
    assert "error" in r
    assert "不支持" in r["error"]


def test_read_image_too_large(tmp_path, monkeypatch):
    f = tmp_path / "huge.png"
    f.write_bytes(b"\x89PNG" + b"\x00" * 100)
    monkeypatch.setattr(Path, "stat", lambda self: type("S", (), {"st_size": 6_000_000})())
    r = nt._read_image(str(f))
    assert "error" in r
    assert "5MB" in r["error"]


def test_read_image_empty_file(tmp_path):
    f = tmp_path / "empty.png"
    f.write_bytes(b"")
    r = nt._read_image(str(f))
    assert "error" in r


def test_read_image_success(tmp_path):
    # 1x1 red pixel PNG (smallest valid PNG)
    import struct, zlib
    def _minimal_png():
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr = _png_chunk(b"IHDR", ihdr_data)
        raw_row = b"\x00\xff\x00\x00"  # filter=None, R=255 G=0 B=0
        idat = _png_chunk(b"IDAT", zlib.compress(raw_row))
        iend = _png_chunk(b"IEND", b"")
        return sig + ihdr + idat + iend
    def _png_chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    f = tmp_path / "red.png"
    f.write_bytes(_minimal_png())
    r = nt._read_image(str(f))
    assert "error" not in r
    assert r["media_type"] == "image/png"
    assert "_vision_block" in r
    assert len(r["_vision_block"]) == 2
    assert r["_vision_block"][1]["type"] == "image_url"
    assert r["_vision_block"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_read_image_jpeg(tmp_path):
    f = tmp_path / "test.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
    r = nt._read_image(str(f))
    assert "error" not in r
    assert r["media_type"] == "image/jpeg"


def test_execution_cap_registers_read_image():
    cap = capabilities.build(["execution"], agent_id="xi")
    names = {d["function"]["name"] for d in cap["tool_defs"]}
    assert "read_image" in names
    assert "read_image" in cap["dispatch"]


def test_execution_cap_registers_git_tools():
    cap = capabilities.build(["execution"], agent_id="xi")
    names = {d["function"]["name"] for d in cap["tool_defs"]}
    for name in ["git_status", "git_diff", "git_commit", "git_log",
                 "git_branch", "git_create_branch"]:
        assert name in names, f"{name} missing from tool_defs"
        assert name in cap["dispatch"], f"{name} missing from dispatch"
