"""Storage adapters used by the Context Engine.

The application stays local-first: local adapters are always available, while
OSS and Milvus are imported lazily only when the corresponding backend is
selected in ``.env``.
"""

from .base import BlobStore, StoredArtifact, VectorRecord, VectorStore
from .embedding import HashEmbeddingProvider, QwenEmbeddingProvider
from .local_blob_store import LocalBlobStore
from .local_vector_store import LocalVectorStore
from .milvus_vector_store import MilvusVectorStore
from .oss_blob_store import OSSBlobStore

__all__ = [
    "BlobStore",
    "HashEmbeddingProvider",
    "LocalBlobStore",
    "LocalVectorStore",
    "MilvusVectorStore",
    "OSSBlobStore",
    "QwenEmbeddingProvider",
    "StoredArtifact",
    "VectorRecord",
    "VectorStore",
]
