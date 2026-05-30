"""
routes/knowledge.py — 知识库 HTTP 接口（文档列表 / 语义检索 / 上传 / 删除）
"""
import asyncio
from aiohttp import web

from .auth import CORS_HEADERS
from knowledge_base import kb as _kb


async def kb_docs_handler(request):
    """GET /kb/docs — 列出文档（?agent= 只看某 agent 私有 + 共享语料）"""
    agent = request.query.get("agent") or None
    docs = await asyncio.to_thread(_kb.list_docs, agent)
    return web.json_response({"docs": docs}, headers=CORS_HEADERS)


async def kb_search_handler(request):
    """POST /kb/search — 语义检索
    Body: {"query": "...", "top_k": 5, "doc_id": null}
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS_HEADERS)
    query  = body.get("query", "").strip()
    top_k  = int(body.get("top_k", 5))
    doc_id = body.get("doc_id") or None
    agent  = body.get("agent") or None
    if not query:
        return web.json_response({"error": "query is empty"}, status=400, headers=CORS_HEADERS)
    try:
        hits = await asyncio.to_thread(_kb.search, query, top_k, doc_id, agent)
        return web.json_response({"hits": hits}, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


async def kb_upload_handler(request):
    """POST /kb/upload — 上传并入库文件
    multipart/form-data: file=<binary>, name=<display_name>
    或 JSON: {"text": "...", "name": "..."}
    """
    ct = request.content_type or ""
    try:
        if "multipart" in ct:
            reader = await request.multipart()
            text, name = "", ""
            async for part in reader:
                if part.name == "file":
                    raw = await part.read()
                    name = name or part.filename or "未命名文件"
                    try:
                        text = raw.decode("utf-8", errors="replace")
                    except Exception:
                        text = raw.decode("latin-1", errors="replace")
                elif part.name == "name":
                    name = (await part.read()).decode("utf-8", errors="replace")
        agent = request.query.get("agent") or None
        if "multipart" not in ct:
            agent = body.get("agent") or agent

        if not text.strip():
            return web.json_response({"error": "文件内容为空"}, status=400, headers=CORS_HEADERS)

        result = await asyncio.to_thread(_kb.ingest, text, name, None, agent)
        return web.json_response(result, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)


async def kb_delete_handler(request):
    """DELETE /kb/docs/{doc_id} — 删除文档"""
    doc_id = request.match_info["doc_id"]
    result = await asyncio.to_thread(_kb.delete, doc_id)
    if "error" in result:
        return web.json_response(result, status=404, headers=CORS_HEADERS)
    return web.json_response(result, headers=CORS_HEADERS)


async def kb_options_handler(request):
    return web.Response(headers=CORS_HEADERS)


def register(app):
    app.router.add_get("/kb/docs",              kb_docs_handler)
    app.router.add_post("/kb/search",           kb_search_handler)
    app.router.add_post("/kb/upload",           kb_upload_handler)
    app.router.add_delete("/kb/docs/{doc_id}",  kb_delete_handler)
    app.router.add_options("/kb/{tail:.*}",     kb_options_handler)
