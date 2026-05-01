"""M8 vector-store backends — production (Chroma) + in-memory stub.

Per START-PROMPT §5 M8 contract; MASTER §9 (``[ERR_DB]``).

Pure stdlib at module level. ``chromadb`` is imported **inside**
:class:`ChromaVectorStore.__init__` only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

ERR_DB = "[ERR_DB]"


class StoreError(Exception):
    """Raised on vector-store failures.

    Message always begins with ``[ERR_DB]``.
    """


class VectorStore(ABC):
    """Abstract upsert-style vector store."""

    @abstractmethod
    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        documents: list[str],
    ) -> None: ...

    @abstractmethod
    def delete(self, ids: list[str]) -> None: ...

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def reset(self) -> None: ...


class ChromaVectorStore(VectorStore):
    """Production vector store backed by ``chromadb`` PersistentClient."""

    def __init__(
        self,
        index_dir: Path,
        collection_name: str,
        *,
        distance_metric: str,
    ) -> None:
        try:
            import chromadb  # noqa: PLC0415
        except ImportError as exc:
            raise StoreError(
                f"{ERR_DB} chromadb is required;"
                " install with: pip install chromadb"
            ) from exc
        try:
            index_dir = Path(index_dir)
            index_dir.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(index_dir))
            collection = client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": distance_metric},
            )
        except Exception as exc:
            raise StoreError(f"{ERR_DB} failed to open Chroma store: {exc}") from exc
        self._client = client
        self._collection = collection
        self._index_dir = index_dir
        self._collection_name = collection_name
        self._distance_metric = distance_metric

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        documents: list[str],
    ) -> None:
        if not ids:
            return
        try:
            self._collection.upsert(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents,
            )
        except Exception as exc:
            raise StoreError(f"{ERR_DB} upsert failed: {exc}") from exc

    def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        try:
            self._collection.delete(ids=ids)
        except Exception as exc:
            raise StoreError(f"{ERR_DB} delete failed: {exc}") from exc

    def count(self) -> int:
        try:
            return int(self._collection.count())
        except Exception as exc:
            raise StoreError(f"{ERR_DB} count failed: {exc}") from exc

    def reset(self) -> None:
        try:
            self._client.delete_collection(self._collection_name)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": self._distance_metric},
            )
        except Exception as exc:
            raise StoreError(f"{ERR_DB} reset failed: {exc}") from exc


class InMemoryVectorStore(VectorStore):
    """Pure-dict vector store for tests and offline orchestration."""

    def __init__(self) -> None:
        self._records: dict[str, dict] = {}

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        documents: list[str],
    ) -> None:
        if not (len(ids) == len(embeddings) == len(metadatas) == len(documents)):
            raise StoreError(f"{ERR_DB} upsert called with mismatched list lengths")
        for i, _id in enumerate(ids):
            self._records[_id] = {
                "embedding": list(embeddings[i]),
                "metadata": dict(metadatas[i]),
                "document": documents[i],
            }

    def delete(self, ids: list[str]) -> None:
        for _id in ids:
            self._records.pop(_id, None)

    def count(self) -> int:
        return len(self._records)

    def reset(self) -> None:
        self._records.clear()

    # Test helpers ---------------------------------------------------

    def ids(self) -> list[str]:
        return list(self._records.keys())

    def get(self, _id: str) -> dict | None:
        rec = self._records.get(_id)
        if rec is None:
            return None
        return {
            "embedding": list(rec["embedding"]),
            "metadata": dict(rec["metadata"]),
            "document": rec["document"],
        }
