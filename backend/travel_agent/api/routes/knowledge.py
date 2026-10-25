"""
知识库管理 API (Serving Layer)
支持文档上传、索引、查询和删除。

- Upload size cap
- 集合归属由服务端的本地身份解析，客户端不声明所有者
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from travel_agent.bootstrap.registry import get_components
from travel_agent.config.loader import get_settings
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from ...knowledge.collections import CollectionAddressInvalid, normalize_collection, scope_collection
from ...knowledge.sources.document_parse import (
    SUPPORTED_SUFFIXES,
    DocumentRejected,
    parse_upload,
)
from travel_agent.knowledge.text_validation import TextNotIndexable, require_indexable_text
from travel_agent.knowledge.documents import SourceDocumentUnavailable, require_source_document
from travel_agent.api.schemas.knowledge import (
    KnowledgeCollectionStatsResponse,
    KnowledgeDeleteResponse,
    KnowledgeQueryRequest,
    KnowledgeQueryResponse,
    KnowledgeSourceDocumentResponse,
    KnowledgeSourceUpdateRequest,
    KnowledgeUploadRequest,
    KnowledgeUploadResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

# 阈值与判定在 `knowledge/sources/document_parse.py`：上传与批量导入两条入口共用一份，
# 否则扫描版 PDF 在一条路上被拒、在另一条路上变成一次「成功索引 0 个文本块」。


# 这条路上每一个 4xx 都带一个 `code`，**一个都不许少**。少一个的后果不是「少一句话」，
# 是**画成另一句话**：界面读不到 code 就按状态码回落，而 422 那一档的回落是
    # 「请求的信息不完整，请刷新页面后重试」—— 一份损坏的 PDF 刷一百次还是损坏的。
    # `message` 只给日志与其他客户端，**界面自己说话**，
# 那一侧的表在 `frontend/src/lib/knowledgeIngestFailure.ts`，两张表逐条对齐。
#
# `message` 里**不许**出现被 catch 到的异常原文：它是给这台机器看的（已经进
# `logger.warning`），发出去只会变成一句没人能照着做的话。

# 每一种 code 对应的 HTTP 状态码与那句给日志的话。上限值从 `IngestConfig` 读，
# 不在这里再写一遍。
_REJECTION_STATUS = {
    "unsupported_file_type": 400,
    "file_too_large": 413,
    "document_unreadable": 422,
    "document_too_complex": 422,
    "document_parse_timeout": 422,
    "no_indexable_text": 422,
    "ingest_busy": 503,
}
_REJECTION_MESSAGE = {
    "unsupported_file_type": "这个文件格式不在支持范围内",
    "file_too_large": "文件超过大小上限",
    "document_unreadable": "这份文档打不开，文件内容可能已损坏或不是它声称的格式",
    "document_too_complex": "这份文档超出了解析上限（页数、条目数或展开后的体积）",
    "document_parse_timeout": "这份文档在解析上限内没能读完",
    "no_indexable_text": "没有可索引的正文（可能是空文件或扫描版 PDF）",
    "ingest_busy": "正在解析的文档太多，稍后再试",
}


def _require_vector_knowledge() -> None:
    if not get_settings().embedding.enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "knowledge_disabled", "message": "向量知识库已由配置关闭"},
        )


def _logical_collection_name(collection: str) -> str:
    """Project the shared collection contract to an HTTP 400 boundary."""
    try:
        return normalize_collection(collection)
    except CollectionAddressInvalid as exc:
        logger.warning("资料库集合名不合法: %s", exc)
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc





def _require_indexable_text(text: str) -> str:
    try:
        return require_indexable_text(text)
    except TextNotIndexable as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc


def _rejection_to_http(rejection: DocumentRejected) -> HTTPException:
    """把解析边界的判决投影到 HTTP，**不转发解析器的原话**。

    界面那一侧按 code 分辨失败种类，读不到就只能按状态码回落到「请求的信息不完整，
    请刷新页面后重试」，而请求是完整的、刷新也不会让一份损坏的 PDF 变好。解析器那句
    原话（`Stream has ended unexpectedly` / `File is not a zip file`）已经进了
    `document_parse` 的日志，那是它该待的地方。
    """

    code = rejection.code
    return HTTPException(
        status_code=_REJECTION_STATUS.get(code, 422),
        detail={
            "code": code,
            "message": _REJECTION_MESSAGE.get(code, "这份文档没能进入资料库"),
        },
    )


@router.post("/index", response_model=KnowledgeUploadResponse)
async def index_text(request: KnowledgeUploadRequest):
    """将文本内容索引到知识库（用户作用域集合）。"""
    _require_vector_knowledge()
    logical_collection = _logical_collection_name(request.collection)
    collection = scope_collection(logical_collection)
    # 手输那一路和上传文件走同一道界：空内容不许换来一句「成功索引 0 个文本块」。
    _require_indexable_text(request.content or "")
    components = get_components()
    try:
        count = await components.knowledge_indexer.index_text(
            text=request.content,
            source=request.source,
            collection=collection,
            metadata={**(request.metadata or {}), "owner_user_id": LOCAL_USER_ID},
        )
        return KnowledgeUploadResponse(
            chunks_indexed=count,
            collection=logical_collection,
            message=f"成功索引 {count} 个文本块",
        )
    except Exception as e:
        logger.error(f"知识库索引失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload-file", response_model=KnowledgeUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    collection: str = Form("default"),
    source: str = Form(""),
):
    """上传文件并索引到知识库（支持 .txt / .md / .pdf / .docx）。

    所有输入边界（类型、字节数、页数、ZIP 展开量与压缩比、解析超时）都在
    `knowledge/sources/document_parse.py` 一处判定，这条路只负责把判决投影成 HTTP。
    """
    _require_vector_knowledge()
    ingest = get_settings().ingest
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_file_type",
                "message": _REJECTION_MESSAGE["unsupported_file_type"],
            },
        )

    # 先看 content-length 再看真读进来多少：前者能在读进内存之前拒掉一份超限文件。
    # 413 必须带 code：界面那张按状态码说话的表没有 413 这一档时，一份超限文件
    # 只会换来「无法连接服务，请检查网络」。带上 code 之后它有自己的一句话。
    declared = file.headers.get("content-length") if file.headers else None
    if declared is not None:
        try:
            if int(declared) > ingest.max_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail={
                        "code": "file_too_large",
                        "message": _REJECTION_MESSAGE["file_too_large"],
                    },
                )
        except ValueError:
            pass

    raw = await file.read(ingest.max_upload_bytes + 1)
    try:
        parsed = await parse_upload(raw, suffix)
    except DocumentRejected as exc:
        raise _rejection_to_http(exc) from exc
    if parsed.truncated:
        logger.warning(
            "上传正文被截断 | file=%s limit=%d",
            file.filename,
            ingest.max_extracted_chars,
        )
    text = _require_indexable_text(parsed.text)
    source_name = source or file.filename or "uploaded_file"
    logical_collection = _logical_collection_name(collection)
    scoped = scope_collection(logical_collection)

    components = get_components()
    try:
        count = await components.knowledge_indexer.index_text(
            text=text,
            source=source_name,
            collection=scoped,
            metadata={"owner_user_id": LOCAL_USER_ID, "filename": file.filename or ""},
        )
        return KnowledgeUploadResponse(
            chunks_indexed=count,
            collection=logical_collection,
            message=f"文件 [{file.filename}] 已成功索引 {count} 个文本块",
        )
    except Exception as e:
        logger.error(f"文件索引失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query", response_model=KnowledgeQueryResponse)
async def query_knowledge(request: KnowledgeQueryRequest):
    """语义查询知识库（仅当前用户作用域集合）。"""
    _require_vector_knowledge()
    collection = scope_collection(_logical_collection_name(request.collection))
    components = get_components()
    try:
        docs = await components.vector_retriever.retrieve(
            query=request.query,
            collection=collection,
            top_k=request.top_k,
        )
        return KnowledgeQueryResponse(results=docs, total=len(docs))
    except Exception as e:
        logger.error(f"知识库查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/collection/{collection_name}", response_model=KnowledgeDeleteResponse)
async def delete_collection(collection_name: str):
    """删除指定集合。"""
    logical_collection = _logical_collection_name(collection_name)
    scoped = scope_collection(logical_collection)
    components = get_components()
    try:
        count = await components.knowledge_indexer.delete_collection(scoped)
        return KnowledgeDeleteResponse(
            collection=logical_collection,
            deleted_chunks=count,
            message=f"已删除资料库的 {count} 个文档块",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _require_source_document(collection: str, source: str) -> dict:
    try:
        return await require_source_document(get_components().knowledge_indexer, collection, source)
    except SourceDocumentUnavailable as exc:
        raise HTTPException(
            status_code=409 if exc.code == "document_text_unavailable" else 404,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.get(
    "/collections/{collection_name}/source",
    response_model=KnowledgeSourceDocumentResponse,
)
async def get_source_document(
    collection_name: str,
    source: str = Query(..., min_length=1, description="来源名，就是列表里显示的那一行"),
):
    """读一篇资料的正文（用户作用域）。

    来源名走查询参数而不是路径段：它是用户给的文件名，可以带斜杠、点、空格 ——
    放进路径就要跟路由分段规则打架，而一个被路由切开的来源名会变成一次 404。
    """
    logical_collection = _logical_collection_name(collection_name)
    scoped = scope_collection(logical_collection)
    document = await _require_source_document(scoped, source)
    return KnowledgeSourceDocumentResponse(
        collection=logical_collection, **document
    )


@router.put(
    "/collections/{collection_name}/source",
    response_model=KnowledgeUploadResponse,
)
async def update_source_document(
    collection_name: str,
    request: KnowledgeSourceUpdateRequest,
    source: str = Query(..., min_length=1),
):
    """改写一篇资料的正文，并按新正文重新分段入库。

    **保存就是重新入库**：正文覆盖写、旧段全删、新段重算（会重新调 embedding，
    contextual 分块还会逐段调一次 fast 模型）。只改正文不重算段的话，屏幕上是新正文、
    规划时参考的仍是旧内容 —— 那是这个仓明令禁止的半修。

    先确认这一篇存在再写：这个接口是「改」不是「建」，让它顺手建一篇会让一个打错的
    来源名静默变成一篇新资料。
    """
    _require_vector_knowledge()
    logical_collection = _logical_collection_name(collection_name)
    scoped = scope_collection(logical_collection)
    await _require_source_document(scoped, source)
    # 手输那一路、上传那一路、改写这一路共用同一道正文下界。
    content = _require_indexable_text(request.content or "")
    components = get_components()
    try:
        count = await components.knowledge_indexer.index_text(
            text=content,
            source=source,
            collection=scoped,
            metadata={"owner_user_id": LOCAL_USER_ID},
        )
        return KnowledgeUploadResponse(
            chunks_indexed=count,
            collection=logical_collection,
            message=f"已重新整理成 {count} 个文本块",
        )
    except Exception as e:
        logger.error(f"资料改写失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/collections/{collection_name}/source",
    response_model=KnowledgeDeleteResponse,
)
async def delete_source_document(
    collection_name: str,
    source: str = Query(..., min_length=1),
):
    """删除一篇资料（正文 + 它的全部段）。整库销毁仍走 `/collection/{name}`。"""
    logical_collection = _logical_collection_name(collection_name)
    scoped = scope_collection(logical_collection)
    components = get_components()
    result = await components.knowledge_indexer.delete_source(scoped, source)
    if not result["existed"]:
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_source", "message": "资料库里没有这一篇"},
        )
    deleted = int(result["deleted_chunks"])
    return KnowledgeDeleteResponse(
        collection=logical_collection,
        deleted_chunks=deleted,
        message=f"已删除「{source}」，共 {deleted} 段资料",
    )


@router.get("/collections/{collection_name}/stats", response_model=KnowledgeCollectionStatsResponse)
async def get_collection_stats(collection_name: str):
    """获取集合统计信息（用户作用域）。"""
    logical_collection = _logical_collection_name(collection_name)
    scoped = scope_collection(logical_collection)
    components = get_components()
    try:
        stats = await components.knowledge_indexer.get_collection_stats(scoped)
        return KnowledgeCollectionStatsResponse(collection=logical_collection, **stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
