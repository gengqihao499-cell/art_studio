"""Small contracts that keep local and remote storage interchangeable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class StoredArtifact:
    """Location returned after a blob has been durably stored."""

    backend: str
    uri: str
    size_bytes: int
    content_type: str


@dataclass(slots=True)
class VectorRecord:
    """One searchable long-term memory entry."""

    id: str
    project_id: str
    session_id: str
    memory_type: str
    content: str
    importance: float
    embedding: list[float]


class BlobStore(Protocol):
    name: str

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredArtifact: ...

    def get_bytes(self, uri: str) -> bytes: ...

    def health(self) -> dict: ...


class VectorStore(Protocol):
    name: str

    def upsert(self, records: list[VectorRecord]) -> None: ...

    def search(
        self,
        embedding: list[float],
        *,
        project_id: str,
        limit: int,
    ) -> list[dict]: ...

    def health(self) -> dict: ...


class EmbeddingProvider(Protocol):
    name: str
    dimension: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

    def health(self) -> dict: ...
