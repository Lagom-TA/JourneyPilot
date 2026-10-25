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

    `chunk_count` 与列表那一行印的是同一个数（都来自段表），所以打开一篇资料不会
    看到和列表不一致的段数。
    """

    collection: str
    source: str
    content: str
    chunk_count: int
    updated_at: Optional[datetime] = None


class KnowledgeSourceUpdateRequest(BaseModel):
    """改写一篇资料的正文。

    只有正文 —— 来源名不在这里改：它是这一篇的身份（`(collection, source)` 唯一），
    改名是另一件事，产品目前没有那个入口，所以这里也不留一个没人拨的旋钮。
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
