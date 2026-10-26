"""知识集合的逻辑名与物理名约定。

对外只使用逻辑集合名；物理 PostgreSQL 集合名在服务端派生，不越过 API 与接地边界。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, MutableMapping

from travel_agent.runtime.local_identity import LOCAL_USER_ID

USER_KNOWLEDGE_COLLECTION = "travel_knowledge"

# 出厂语料：由本地可选种子声明，对所有用户相同；公开仓库不携带这些数据。
FACTORY_KNOWLEDGE_COLLECTIONS = (
    "destinations",
    "local_culture",
    "visa_policies",
    "travel_tips",
)


def canonical_logical_collection(collection: str) -> str:
    """返回公开逻辑集合名；物理名直接拒绝。"""

    logical = (collection or "").strip()
    if not logical:
        raise ValueError("collection 无效")
    if logical.startswith("u_") and "__" in logical:
        raise ValueError("collection 必须使用逻辑名称")
    return logical


def user_scoped_collection(logical_collection: str) -> str:
    """把用户集合的逻辑名解析为唯一的内部物理名。"""

    logical = canonical_logical_collection(logical_collection)
    return f"u_{LOCAL_USER_ID}__{logical}"


@dataclass(frozen=True)
class GroundingCorpus:
    """一次接地检索要查哪些集合，以及每个物理名的公开逻辑名。

    用户上传的资料库与出厂语料在同一次检索里一起打分、融合、精排，由排名决定
    谁进 prompt，因此这里给出的是一张探针清单，而不是主集合与备用集合两档。

    ``probe_collections`` 是检索层使用的物理名（``u_local__travel_knowledge``），
    ``logical_name`` 是任何对外可见位置必须使用的公开名。两者放在同一个对象上，
    保证「查哪张表」与「对外叫什么」不会各自漂移。
    """

    probe_collections: tuple[str, ...]
    user_probe: str
    _logical_by_probe: Mapping[str, str]

    def logical_name(self, probe_collection: str) -> str:
        """把一个探针名翻回公开逻辑名（出厂集合本来就是逻辑名，原样返回）。"""

        return self._logical_by_probe.get(probe_collection, probe_collection)

    @property
    def logical_collections(self) -> tuple[str, ...]:
        """本轮查过的集合，全部以公开逻辑名表示（可直接进摘要与日志）。"""

        return tuple(self.logical_name(probe) for probe in self.probe_collections)

    def is_user_owned(self, logical_collection: str) -> bool:
        """这个**逻辑**集合名是不是用户自己上传的那一个。"""

        return logical_collection == USER_KNOWLEDGE_COLLECTION


def grounding_corpus() -> GroundingCorpus:
    """查询所有允许的集合，不依赖可选的种子清单。"""

    probes = list(FACTORY_KNOWLEDGE_COLLECTIONS)
    user_probe = user_scoped_collection(USER_KNOWLEDGE_COLLECTION)
    probes.append(user_probe)
    return GroundingCorpus(
        probe_collections=tuple(probes),
        user_probe=user_probe,
        _logical_by_probe={user_probe: USER_KNOWLEDGE_COLLECTION},
    )


def relabel_to_logical_collections(
    docs: Iterable[MutableMapping[str, Any]], corpus: GroundingCorpus
) -> None:
    """把检索层写在 doc 上的探针名改成公开逻辑名，就地修改。

    物理名带 owner id，只能作为检索地址；对外可见的 coverage、SourceRecord
    snapshot 与日志必须使用逻辑名。翻译只在接地边界做这一次。
    """

    for doc in docs:
        probe = str(doc.get("collection") or "")
        if probe:
            doc["collection"] = corpus.logical_name(probe)


class CollectionAddressInvalid(ValueError):
    code = "collection_address_invalid"
    message = "资料库地址不是一个合法的逻辑集合名"


def normalize_collection(collection: str) -> str:
    try:
        return canonical_logical_collection(collection)
    except ValueError as exc:
        raise CollectionAddressInvalid(str(exc)) from exc


def scope_collection(collection: str) -> str:
    """把校验过的逻辑名解析为当前用户的集合。"""
    return user_scoped_collection(normalize_collection(collection))
