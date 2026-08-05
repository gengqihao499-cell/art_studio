"""Local deterministic and Qwen text embedding providers."""

from __future__ import annotations

import hashlib
import math

import httpx


class HashEmbeddingProvider:
    """No-cost deterministic embeddings for local development.

    They are not a replacement for a semantic model, but they let the complete
    storage/retrieval pipeline run offline and make integration tests stable.
    """

    name = "hash"

    def __init__(self, dimension: int = 768) -> None:
        self.dimension = max(32, dimension)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        normalized = " ".join(text.lower().split())
        tokens = [normalized[index : index + 3] for index in range(max(1, len(normalized) - 2))]
        for token in tokens or [normalized]:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def health(self) -> dict:
        return {"available": True, "backend": self.name, "dimension": self.dimension}


class QwenEmbeddingProvider:
    """Synchronous Beijing-region ``text-embedding-v4`` adapter."""

    name = "qwen"

    def __init__(
        self,
        *,
        api_key: str,
        workspace_id: str,
        api_host: str = "",
        model: str = "text-embedding-v4",
        dimension: int = 768,
        timeout_seconds: float = 30,
    ) -> None:
        if not api_key or (not workspace_id and not api_host):
            raise RuntimeError("Qwen embeddings require API Key and Workspace ID or API Host")
        base = api_host.strip().rstrip("/") or f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com"
        self.url = f"{base}/compatible-mode/v1/embeddings"
        self.model = model
        self.dimension = dimension
        self._api_key = api_key
        self._client = httpx.Client(timeout=timeout_seconds)

    def _call(self, texts: list[str]) -> list[list[float]]:
        response = self._client.post(
            self.url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": self.model, "input": texts, "dimensions": self.dimension},
        )
        response.raise_for_status()
        payload = response.json()
        return [list(item["embedding"]) for item in payload.get("data", [])]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._call(texts)

    def embed_query(self, text: str) -> list[float]:
        vectors = self._call([text])
        if not vectors:
            raise RuntimeError("Qwen embedding response contained no vector")
        return vectors[0]

    def health(self) -> dict:
        return {
            "available": True,
            "configured": True,
            "backend": self.name,
            "model": self.model,
            "dimension": self.dimension,
        }

    def close(self) -> None:
        self._client.close()
