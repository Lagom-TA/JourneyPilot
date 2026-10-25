from __future__ import annotations

import hashlib
import json
import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import text

from ..config.loader import get_settings
from ..paths import REPO_ROOT
from ..storage.database import get_db_session
from .collections import FACTORY_KNOWLEDGE_COLLECTIONS

logger = logging.getLogger(__name__)

SEED_SCHEMA = "journeypilot.factory_corpus_seed.v1"

DEFAULT_SEED_DIR = REPO_ROOT / "data" / "corpus" / "seed"
CHUNKS_FILE = "factory-chunks.jsonl"
VECTORS_FILE = "factory-vectors.f32"
MANIFEST_FILE = "manifest.json"

# 一次 executemany 的行数。3000 行一次性提交会让单条 INSERT 语句的参数表大到
# 驱动层重新规划，分批反而更快，也让失败时的回滚范围小一点。
_INSERT_BATCH = 200


def embedder_identity(settings: Any = None) -> str:
    """当前配置声明的 embedding 身份，**不实例化 embedder**。

    不实例化是刻意的：`get_embedder()` 对 qwen3 会去 huggingface 拉 1.2 GB 权重，
    而这个函数在「种子该不该用」这个判断里被调用 —— 判断本身不该有这种副作用。
    """

    cfg = (settings or get_settings()).embedding
    return f"{cfg.provider}:{cfg.model_name or ''}:{int(cfg.dimensions)}"


@dataclass(frozen=True)
class SeedManifest:
    schema: str
    embedder: str
    dimensions: int
    chunk_count: int
    collections: Dict[str, int]
    chunks_sha256: str
    vectors_sha256: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "embedder": self.embedder,
            "dimensions": self.dimensions,
            "chunk_count": self.chunk_count,
            "collections": self.collections,
            "chunks_sha256": self.chunks_sha256,
            "vectors_sha256": self.vectors_sha256,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "SeedManifest":
        return cls(
            schema=str(payload["schema"]),
            embedder=str(payload["embedder"]),
            dimensions=int(payload["dimensions"]),
            chunk_count=int(payload["chunk_count"]),
            collections={str(k): int(v) for k, v in dict(payload["collections"]).items()},
            chunks_sha256=str(payload["chunks_sha256"]),
            vectors_sha256=str(payload["vectors_sha256"]),
        )


@dataclass
class LoadReport:
    """一次开机自举的结果。`problems` 非空 = 该报降级。"""

    loaded: Dict[str, int] = field(default_factory=dict)
    present: Dict[str, int] = field(default_factory=dict)
    reembedded: bool = False
    skipped_non_empty: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_pgvector(raw: str) -> List[float]:
    body = raw.strip()
    if not (body.startswith("[") and body.endswith("]")):
        raise ValueError(f"不是 pgvector 字面量: {raw[:40]!r}")
    inner = body[1:-1].strip()
    if not inner:
        return []
    return [float(part) for part in inner.split(",")]


def _format_pgvector(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------


async def export_seed(seed_dir: Optional[Path] = None) -> SeedManifest:
    """把当前库里的出厂语料写成本地种子。

    行序固定为 `(collection, source, id)`：`id` 只用来排序、**不写进种子**。
    写进去的话，同一份语料在两台机器上重建出来的种子会因为自增序列不同而 hash 不同，
    那这个 hash 就不再是「内容对不对」的判据，只是「谁先建的」。
    """

    target = Path(seed_dir or DEFAULT_SEED_DIR)
    target.mkdir(parents=True, exist_ok=True)

    dimensions = int(get_settings().embedding.dimensions)
    placeholders = ", ".join(f":c{i}" for i in range(len(FACTORY_KNOWLEDGE_COLLECTIONS)))
    params = {f"c{i}": name for i, name in enumerate(FACTORY_KNOWLEDGE_COLLECTIONS)}

    rows: List[Dict[str, Any]] = []
    async with get_db_session() as session:
        result = await session.execute(
            text(
                f"""
                SELECT collection, content, original_content, source,
                       metadata::text AS metadata_text,
                       embedding::text AS embedding_text
                FROM knowledge_chunks
                WHERE collection IN ({placeholders})
                ORDER BY collection, source, id
                """
            ),
            params,
        )
        for record in result.mappings():
            rows.append(dict(record))

    chunks_path = target / CHUNKS_FILE
    vectors_path = target / VECTORS_FILE
    counts: Dict[str, int] = {}

    with chunks_path.open("w", encoding="utf-8", newline="\n") as chunks_handle, \
            vectors_path.open("wb") as vectors_handle:
        for record in rows:
            collection = record["collection"]
            embedding_text = record["embedding_text"]
            if not embedding_text:
                raise RuntimeError(
                    f"collection={collection!r} source={record['source']!r} 的 embedding 为空，"
                    "导出会得到一份查不出东西的种子；先把它重新入库再导"
                )
            vector = _parse_pgvector(embedding_text)
            if len(vector) != dimensions:
                raise RuntimeError(
                    f"向量维度 {len(vector)} 与配置的 {dimensions} 不一致：{record['source']!r}"
                )
            chunks_handle.write(
                json.dumps(
                    {
                        "collection": collection,
                        "source": record["source"],
                        "content": record["content"],
                        "original_content": record["original_content"],
                        "metadata": json.loads(record["metadata_text"] or "{}"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            vectors_handle.write(struct.pack(f"<{dimensions}f", *vector))
            counts[collection] = counts.get(collection, 0) + 1

    manifest = SeedManifest(
        schema=SEED_SCHEMA,
        embedder=embedder_identity(),
        dimensions=dimensions,
        chunk_count=len(rows),
        collections=dict(sorted(counts.items())),
        chunks_sha256=_sha256(chunks_path),
        vectors_sha256=_sha256(vectors_path),
    )
    (target / MANIFEST_FILE).write_text(
        json.dumps(manifest.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


# ---------------------------------------------------------------------------
# 读取与校验
# ---------------------------------------------------------------------------


def read_manifest(seed_dir: Optional[Path] = None) -> Optional[SeedManifest]:
    path = Path(seed_dir or DEFAULT_SEED_DIR) / MANIFEST_FILE
    if not path.exists():
        return None
    return SeedManifest.from_json(json.loads(path.read_text(encoding="utf-8")))


def seeded_factory_collections(seed_dir: Optional[Path] = None) -> Tuple[str, ...]:
    # 清单表示预期内容，不代表数据库里实际已有内容。

    manifest = read_manifest(seed_dir)
    if manifest is None:
        return ()
    return tuple(
        name
        for name in FACTORY_KNOWLEDGE_COLLECTIONS
        if manifest.collections.get(name, 0) > 0
    )


def verify_seed(seed_dir: Optional[Path] = None) -> List[str]:
    """纯文件层自检，返回问题清单（空 = 干净）。不连数据库。"""

    target = Path(seed_dir or DEFAULT_SEED_DIR)
    problems: List[str] = []

    manifest_path = target / MANIFEST_FILE
    chunks_path = target / CHUNKS_FILE
    vectors_path = target / VECTORS_FILE
    for path in (manifest_path, chunks_path, vectors_path):
        if not path.exists():
            problems.append(f"缺文件: {path.name}")
    if problems:
        return problems

    manifest = SeedManifest.from_json(json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.schema != SEED_SCHEMA:
        problems.append(f"schema 不认识: {manifest.schema!r}（本代码认 {SEED_SCHEMA!r}）")

    actual_chunks_hash = _sha256(chunks_path)
    if actual_chunks_hash != manifest.chunks_sha256:
        problems.append(
            f"{CHUNKS_FILE} 内容与 manifest 对不上"
            f"（manifest {manifest.chunks_sha256[:12]}… / 实际 {actual_chunks_hash[:12]}…）"
        )
    actual_vectors_hash = _sha256(vectors_path)
    if actual_vectors_hash != manifest.vectors_sha256:
        problems.append(
            f"{VECTORS_FILE} 内容与 manifest 对不上"
            f"（manifest {manifest.vectors_sha256[:12]}… / 实际 {actual_vectors_hash[:12]}…）"
        )

    line_count = sum(1 for _ in chunks_path.open("r", encoding="utf-8"))
    if line_count != manifest.chunk_count:
        problems.append(f"{CHUNKS_FILE} 有 {line_count} 行，manifest 说 {manifest.chunk_count} 段")

    expected_bytes = manifest.chunk_count * manifest.dimensions * 4
    actual_bytes = vectors_path.stat().st_size
    if actual_bytes != expected_bytes:
        problems.append(
            f"{VECTORS_FILE} 是 {actual_bytes} 字节，"
            f"{manifest.chunk_count} 段 × {manifest.dimensions} 维 × 4 应当是 {expected_bytes} 字节"
        )

    declared_total = sum(manifest.collections.values())
    if declared_total != manifest.chunk_count:
        problems.append(
            f"manifest 分集合计数合计 {declared_total}，与 chunk_count {manifest.chunk_count} 不符"
        )

    unknown = set(manifest.collections) - set(FACTORY_KNOWLEDGE_COLLECTIONS)
    if unknown:
        problems.append(f"种子里有不属于出厂语料的集合: {sorted(unknown)}")

    return problems


def _read_rows(seed_dir: Path, manifest: SeedManifest) -> List[Dict[str, Any]]:
    chunks_path = seed_dir / CHUNKS_FILE
    vectors_path = seed_dir / VECTORS_FILE
    stride = manifest.dimensions * 4
    rows: List[Dict[str, Any]] = []
    with chunks_path.open("r", encoding="utf-8") as chunks_handle, \
            vectors_path.open("rb") as vectors_handle:
        for line in chunks_handle:
            payload = json.loads(line)
            raw = vectors_handle.read(stride)
            if len(raw) != stride:
                raise RuntimeError(
                    f"{VECTORS_FILE} 在第 {len(rows) + 1} 段处提前结束；先跑 --verify"
                )
            payload["vector"] = list(struct.unpack(f"<{manifest.dimensions}f", raw))
            rows.append(payload)
    return rows


# ---------------------------------------------------------------------------
# 灌库
# ---------------------------------------------------------------------------


async def factory_collection_counts() -> Dict[str, int]:
    placeholders = ", ".join(f":c{i}" for i in range(len(FACTORY_KNOWLEDGE_COLLECTIONS)))
    params = {f"c{i}": name for i, name in enumerate(FACTORY_KNOWLEDGE_COLLECTIONS)}
    counts = {name: 0 for name in FACTORY_KNOWLEDGE_COLLECTIONS}
    async with get_db_session() as session:
        result = await session.execute(
            text(
                f"""
                SELECT collection, count(*) AS total
                FROM knowledge_chunks
                WHERE collection IN ({placeholders})
                GROUP BY collection
                """
            ),
            params,
        )
        for record in result.mappings():
            counts[record["collection"]] = int(record["total"])
    return counts


async def load_seed(
    seed_dir: Optional[Path] = None,
    *,
    force: bool = False,
) -> LoadReport:
    """把种子灌进库。默认只补当前为空的出厂集合；`force` 才清空重灌。"""

    target = Path(seed_dir or DEFAULT_SEED_DIR)
    report = LoadReport()

    problems = verify_seed(target)
    if problems:
        report.problems.extend(problems)
        report.present = await factory_collection_counts()
        return report

    manifest = read_manifest(target)
    assert manifest is not None  # verify_seed 已经确认过文件在

    counts = await factory_collection_counts()
    if force:
        wanted = [name for name in manifest.collections if manifest.collections[name] > 0]
    else:
        wanted = [
            name
            for name, declared in manifest.collections.items()
            if declared > 0 and counts.get(name, 0) == 0
        ]
        report.skipped_non_empty = sorted(
            name
            for name, declared in manifest.collections.items()
            if declared > 0 and counts.get(name, 0) > 0
        )

    if not wanted:
        report.present = counts
        return report

    rows = [row for row in _read_rows(target, manifest) if row["collection"] in set(wanted)]

    current = embedder_identity()
    if current != manifest.embedder:
        # 灌进来的向量必须和**查询时**用的 embedder 出自同一个空间，否则余弦是噪声，
        # 而且不报错。所以身份不符时重算，不是「尽量用现成的」。
        logger.warning(
            "出厂语料种子由 %s 生成，当前配置是 %s —— 丢弃种子里的向量，用当前 embedder 重算 %d 段",
            manifest.embedder,
            current,
            len(rows),
        )
        from ..llm.embedder import get_embedder

        embedder = get_embedder()
        vectors = await embedder.embed_batch([row["content"] for row in rows])
        for row, vector in zip(rows, vectors):
            row["vector"] = list(vector)
        report.reembedded = True

    async with get_db_session() as session:
        if force:
            for name in wanted:
                await session.execute(
                    text("DELETE FROM knowledge_chunks WHERE collection = :col"),
                    {"col": name},
                )
        statement = text(
            """
            INSERT INTO knowledge_chunks
                (collection, content, original_content, source, metadata, embedding)
            VALUES
                (:collection, :content, :original_content, :source,
                 CAST(:metadata AS jsonb), CAST(:embedding AS vector))
            """
        )
        for start in range(0, len(rows), _INSERT_BATCH):
            batch = rows[start : start + _INSERT_BATCH]
            await session.execute(
                statement,
                [
                    {
                        "collection": row["collection"],
                        "content": row["content"],
                        "original_content": row["original_content"],
                        "source": row["source"],
                        "metadata": json.dumps(row["metadata"], ensure_ascii=False),
                        "embedding": _format_pgvector(row["vector"]),
                    }
                    for row in batch
                ],
            )

    for row in rows:
        report.loaded[row["collection"]] = report.loaded.get(row["collection"], 0) + 1
    report.present = await factory_collection_counts()
    return report


async def ensure_factory_corpus(seed_dir: Optional[Path] = None) -> LoadReport:
    """开机自举入口：缺什么补什么，补不上就把话说明白。

    「补不上」的判据只看**种子声称有货的集合**（`seeded_factory_collections()`）：
    `visa_policies` 是一个刻意留空的已知缺口，
    把它算进降级只会训练运营者忽略这行日志。
    """

    report = await load_seed(seed_dir, force=False)
    manifest = read_manifest(seed_dir)
    if manifest is None:
        # 整个种子目录都不在时，「缺 manifest.json / 缺 chunks / 缺 vectors」三行是同一件事
        # 说三遍，而运营者要的是能照着做的那一句。**换掉**而不是追加：一条结论配三行噪声，
        # 读的人会把整段当噪声。
        report.problems = [
            f"未提供本地出厂语料种子（{Path(seed_dir or DEFAULT_SEED_DIR)}）——知识库将是空的，"
            "检索会静默返回 0 条；需要时运行 `python backend/scripts/factory_corpus_seed.py --export` 生成"
        ]
        return report

    for name in seeded_factory_collections(seed_dir):
        if report.present.get(name, 0) == 0:
            report.problems.append(
                f"出厂集合 {name} 仍然是空的（种子里有 {manifest.collections[name]} 段）"
            )
    return report
