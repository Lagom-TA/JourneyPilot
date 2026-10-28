"""
结构化文档导入 (Application Layer)
支持 Markdown / TXT / JSON / PDF / DOCX 格式的知识库数据导入。

PDF/DOCX 走 `document_parse.py`：批量导入与上传共用同一组输入边界与同一个受限
解析子进程，避免批量导入绕过上传时施加的限制。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from .document_parse import DocumentRejected, has_indexable_text, parse_file

logger = logging.getLogger(__name__)


class DocumentLoader:
    """
    批量文档加载器。
    支持从本地目录批量导入文档到知识库。
    """

    async def load_directory(
        self,
        directory: str,
        collection: str = "default",
        extensions: List[str] = None,
    ) -> Dict[str, int]:
        """
        扫描目录中的文档并批量索引。
        支持的格式见默认扩展名；返回：{"indexed": N, "failed": M, "files": K}
        """
        from ..indexer import KnowledgeIndexer
        indexer = KnowledgeIndexer()

        exts = extensions or [".txt", ".md", ".json", ".pdf", ".docx"]
        path = Path(directory)
        if not path.exists():
            logger.warning(f"目录不存在: {directory}")
            return {"indexed": 0, "failed": 0, "files": 0}

        files = [f for f in path.rglob("*") if f.suffix.lower() in exts]
        logger.info(f"发现 {len(files)} 个文档待索引")

        indexed_total = 0
        failed = 0
        for file_path in files:
            try:
                docs = await self._load_file(file_path)
                count = await indexer.index_documents(docs, collection=collection)
                indexed_total += count
                logger.debug(f"已索引: {file_path.name} → {count} 个块")
            except Exception as e:
                logger.error(f"文件索引失败 [{file_path}]: {e}")
                failed += 1

        return {"indexed": indexed_total, "failed": failed, "files": len(files)}

    async def load_file(
        self,
        file_path: str,
        collection: str = "default",
    ) -> int:
        """加载单个文件并索引，返回 chunk 数量"""
        from ..indexer import KnowledgeIndexer
        indexer = KnowledgeIndexer()

        path = Path(file_path)
        docs = await self._load_file(path)
        return await indexer.index_documents(docs, collection=collection)

    # -----------------------------------------------------------------------
    # 内部辅助
    # -----------------------------------------------------------------------

    async def _load_file(self, path: Path) -> List[Dict[str, Any]]:
        """将文件内容解析为文档列表"""
        suffix = path.suffix.lower()
        source = str(path)

        if suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                docs = []
                for item in data:
                    if isinstance(item, dict):
                        text = item.get("content") or self._dict_to_text(item)
                        docs.append({
                            "content": text,
                            "source": source,
                            "metadata": {k: v for k, v in item.items() if k != "content"},
                        })
                return docs
            else:
                return [{"content": json.dumps(data, ensure_ascii=False), "source": source}]

        try:
            parsed = await parse_file(path)
        except DocumentRejected as exc:
            raise ValueError(f"文档解析被拒（{exc.code}）：{path.name}") from exc
        if not has_indexable_text(parsed.text):
            # 扫描版 PDF 是这条路上最常见的一种：pypdf 不报错、逐页返回空串。
            # 不拦截时会得到一次「成功索引 0 个块」，并被计进 indexed。
            raise ValueError(f"未提取到可索引正文：{path.name}")
        if parsed.truncated:
            logger.warning("批量导入正文被截断 [%s]", path)
        return [
            {
                "content": parsed.text,
                "source": source,
                "metadata": {"file": path.name},
            }
        ]

    def _dict_to_text(self, d: Dict[str, Any]) -> str:
        """将字典转换为自然语言文本"""
        parts = []
        for k, v in d.items():
            if isinstance(v, list):
                v = "、".join(str(x) for x in v)
            parts.append(f"{k}：{v}")
        return "\n".join(parts)
