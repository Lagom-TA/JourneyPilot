"""
知识库管理 API (Serving Layer)
支持文档上传、索引、查询和删除。

- 上传大小上限
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

# 阈值与判定在 `knowledge/sources/document_parse.py`，上传与批量导入共用同一份。

# 本模块的每个 4xx 都带 `code`：界面按 code 识别失败类型，缺少 code 时按状态码
# 回落，422 会显示为「请求的信息不完整」，与文档解析失败不符。
# 前端对照表在 `frontend/src/features/knowledge/model/knowledgeIngestFailure.ts`。
#
# `message` 不得包含被捕获的异常原文；异常已写入 `logger.warning`。

# 每种 code 对应的 HTTP 状态码与日志文案。上限值从 `IngestConfig` 读取，
# 不在此重复定义。
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
    """将共享集合契约投影到 HTTP 400 边界。"""
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
    """把解析边界的拒绝结果投影为 HTTP 响应，不转发解析器原文。

    界面按 code 区分失败类型；解析器原文已记录在 `document_parse` 的日志中。
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
    # 手输内容与上传文件共用同一正文下界校验。
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

    # 先检查 content-length 再读取正文，可在读入内存前拒绝超限文件。
    # 413 响应必须带 code，界面才能显示对应的提示文案。
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
    """读取一篇资料的正文（用户作用域）。

    来源名通过查询参数传递：文件名可能包含斜杠、点和空格，放进路径段会被路由
    规则切断并导致 404。
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

    保存即重新入库：覆盖正文、删除旧段并重新计算新段（会重新调用 embedding；
    contextual 分块还会逐段调用 fast 模型）。只改正文不重算分段，会导致展示内容
    与规划参考内容不一致。

    先确认资料存在再写入：该接口只修改已有资料，不会创建新资料。
    """
    _require_vector_knowledge()
    logical_collection = _logical_collection_name(collection_name)
    scoped = scope_collection(logical_collection)
    await _require_source_document(scoped, source)
    # 手输、上传与改写共用同一正文下界校验。
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
