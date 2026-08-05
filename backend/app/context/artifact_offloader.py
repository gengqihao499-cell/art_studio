"""Layer 1: replace large observations with durable artifact references."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from app.database import Database
from app.storage.base import BlobStore


class ArtifactOffloader:
    def __init__(
        self,
        database: Database,
        blob_store: BlobStore,
        inline_char_limit: int = 4000,
        preview_chars: int = 420,
    ) -> None:
        self.database = database
        self.blob_store = blob_store
        self.inline_char_limit = max(500, inline_char_limit)
        self.preview_chars = max(100, preview_chars)

    def offload_text(
        self,
        text: str,
        *,
        project_id: str,
        session_id: str,
        run_id: str | None,
        artifact_type: str,
    ) -> dict | None:
        if len(text) <= self.inline_char_limit:
            return None
        raw = text.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        artifact_id = f"ctx_{digest[:20]}"
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM context_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        if existing:
            return self._reference(dict(existing))
        key = f"{project_id}/{session_id}/{artifact_id}.txt"
        stored = self.blob_store.put_bytes(key, raw, "text/plain; charset=utf-8")
        row = {
            "id": artifact_id,
            "project_id": project_id,
            "session_id": session_id,
            "run_id": run_id,
            "artifact_type": artifact_type,
            "storage_backend": stored.backend,
            "uri": stored.uri,
            "preview": text[: self.preview_chars] + "…",
            "sha256": digest,
            "size_bytes": stored.size_bytes,
            "content_type": stored.content_type,
            "created_at": datetime.now(UTC).isoformat(),
        }
        with self.database.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO context_artifacts
                (id, project_id, session_id, run_id, artifact_type, storage_backend,
                 uri, preview, sha256, size_bytes, content_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(row.values()),
            )
        return self._reference(row)

    @staticmethod
    def _reference(row: dict) -> dict:
        return {
            "artifact_id": row["id"],
            "artifact_type": row["artifact_type"],
            "preview": row["preview"],
            "uri": row["uri"],
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
        }

    def offload_json(self, value: object, **metadata) -> dict | None:
        return self.offload_text(
            json.dumps(value, ensure_ascii=False, default=str),
            **metadata,
        )
