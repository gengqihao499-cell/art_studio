"""SQLite vector adapter for a zero-infrastructure local fallback."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

from app.database import Database
from app.storage.base import VectorRecord


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return -1.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
    return dot / (left_norm * right_norm)


class LocalVectorStore:
    name = "local"

    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        timestamp = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            connection.executemany(
                """INSERT INTO memory_vectors
                (id, project_id, session_id, memory_type, content, importance,
                 embedding_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET content = excluded.content,
                importance = excluded.importance, embedding_json = excluded.embedding_json,
                updated_at = excluded.updated_at""",
                [
                    (
                        item.id,
                        item.project_id,
                        item.session_id,
                        item.memory_type,
                        item.content,
                        item.importance,
                        json.dumps(item.embedding),
                        timestamp,
                    )
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
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_vectors WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        ranked = []
        for row in rows:
            score = _cosine(embedding, json.loads(row["embedding_json"]))
            ranked.append(
                {
                    "id": row["id"],
                    "memory_type": row["memory_type"],
                    "content": row["content"],
                    "importance": float(row["importance"]),
                    "score": score,
                }
            )
        ranked.sort(key=lambda item: (item["score"], item["importance"]), reverse=True)
        return ranked[: max(0, limit)]

    def health(self) -> dict:
        return {"available": True, "backend": self.name, "database": "sqlite"}
