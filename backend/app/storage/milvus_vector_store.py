"""Optional Milvus/Zilliz Cloud vector adapter."""

from __future__ import annotations

from app.storage.base import VectorRecord


class MilvusVectorStore:
    name = "milvus"

    def __init__(
        self,
        *,
        uri: str,
        token: str,
        collection: str = "artflow_memories",
        dimension: int = 768,
    ) -> None:
        if not uri or not token:
            raise RuntimeError("Milvus backend requires URI and token")
        self.uri = uri
        self.token = token
        self.collection = collection
        self.dimension = dimension
        self._client = None

    def _connect(self):
        if self._client is None:
            try:
                from pymilvus import DataType, MilvusClient
            except ImportError as exc:
                raise RuntimeError("Milvus backend requires: pip install pymilvus") from exc
            self._client = MilvusClient(uri=self.uri, token=self.token)
            if not self._client.has_collection(collection_name=self.collection):
                schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
                schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=96)
                schema.add_field("project_id", DataType.VARCHAR, max_length=96)
                schema.add_field("session_id", DataType.VARCHAR, max_length=96)
                schema.add_field("memory_type", DataType.VARCHAR, max_length=64)
                schema.add_field("content", DataType.VARCHAR, max_length=8192)
                schema.add_field("importance", DataType.FLOAT)
                schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.dimension)
                indexes = self._client.prepare_index_params()
                indexes.add_index("embedding", index_type="AUTOINDEX", metric_type="COSINE")
                self._client.create_collection(
                    collection_name=self.collection,
                    schema=schema,
                    index_params=indexes,
                )
        return self._client

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        self._connect().upsert(
            collection_name=self.collection,
            data=[
                {
                    "id": item.id,
                    "project_id": item.project_id,
                    "session_id": item.session_id,
                    "memory_type": item.memory_type,
                    "content": item.content[:8192],
                    "importance": float(item.importance),
                    "embedding": item.embedding,
                }
                for item in records
            ],
        )

    def search(
        self,
        embedding: list[float],
        *,
        project_id: str,
        limit: int,
    ) -> list[dict]:
        safe_project_id = project_id.replace('"', "")
        results = self._connect().search(
            collection_name=self.collection,
            data=[embedding],
            filter=f'project_id == "{safe_project_id}"',
            limit=limit,
            output_fields=["memory_type", "content", "importance"],
        )
        return [
            {
                "id": hit.get("id"),
                "score": float(hit.get("distance", 0.0)),
                **dict(hit.get("entity") or {}),
            }
            for hit in (results[0] if results else [])
        ]

    def health(self) -> dict:
        try:
            client = self._connect()
            client.list_collections()
            return {
                "available": True,
                "backend": self.name,
                "collection": self.collection,
                "dimension": self.dimension,
            }
        except Exception as exc:
            return {
                "available": False,
                "backend": self.name,
                "collection": self.collection,
                "error": type(exc).__name__,
            }
