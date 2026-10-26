from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from pydantic import BaseModel
from pydantic import Field


class KnowledgeUploadRequest(BaseModel):
    content: str
    source: str = "manual"
    collection: str = "default"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeUploadResponse(BaseModel):
    chunks_indexed: int
    collection: str
    message: str


class KnowledgeSourceDetailResponse(BaseModel):
    source: str
    chunk_count: int
    updated_at: Optional[datetime] = None


class KnowledgeCollectionStatsResponse(BaseModel):
    collection: str
    total: int = 0
    sources: int = 0
    source_details: List[KnowledgeSourceDetailResponse] = Field(default_factory=list)
    oldest: Optional[datetime] = None
    newest: Optional[datetime] = None


class KnowledgeSourceDocumentResponse(BaseModel):
    """一篇资料的正文。

    `chunk_count` 与列表行使用同一来源（段表），打开资料时不会出现段数不一致。
    """

    collection: str
    source: str
    content: str
    chunk_count: int
    updated_at: Optional[datetime] = None


class KnowledgeSourceUpdateRequest(BaseModel):
    """改写一篇资料的正文。

    只包含正文；来源名是资料的标识（`(collection, source)` 唯一），改名不属于
    该接口。
    """

    content: str


class KnowledgeDeleteResponse(BaseModel):
    collection: str
    deleted_chunks: int
    message: str


class KnowledgeQueryRequest(BaseModel):
    query: str
    collection: str = "default"
    top_k: int = 5


class KnowledgeQueryResponse(BaseModel):
    results: List[Dict[str, Any]]
    total: int
