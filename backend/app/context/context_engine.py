"""Coordinator for ArtFlow's five-layer context pipeline.

Canonical messages remain in SQLite. This engine only decides which projection
is sent to a model, and persists addressable artifacts/snapshots so no
compression step has to destroy source data.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from app.context.artifact_offloader import ArtifactOffloader
from app.context.budget_manager import ContextBudgetManager, estimate_tokens
from app.context.claude_memory import ClaudeMemoryStore
from app.context.context_projector import ContextProjector
from app.context.micro_compactor import MicroCompactor
from app.database import Database
from app.storage.base import BlobStore, EmbeddingProvider, VectorRecord, VectorStore


MEMORY_KEYS = (
    "project_goal",
    "locked_constraints",
    "style_decisions",
    "character_facts",
    "composition_facts",
    "rejected_directions",
    "active_image",
    "open_questions",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ContextEngine:
    """Facade consumed by ProjectService, AgentRuntime and API routes."""

    def __init__(
        self,
        *,
        database: Database,
        claude_store: ClaudeMemoryStore,
        blob_store: BlobStore,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        max_tokens: int = 12_000,
        auto_compact_ratio: float = 0.75,
        artifact_inline_chars: int = 4000,
        semantic_top_k: int = 6,
    ) -> None:
        self.database = database
        self.claude_store = claude_store
        self.blob_store = blob_store
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider
        self.semantic_top_k = max(0, semantic_top_k)
        self.budget = ContextBudgetManager(max_tokens, auto_compact_ratio)
        self.offloader = ArtifactOffloader(
            database,
            blob_store,
            inline_char_limit=artifact_inline_chars,
        )
        self.micro_compactor = MicroCompactor(self.offloader)
        self.projector = ContextProjector()

    def prepare_packet(
        self,
        *,
        project_id: str,
        project_name: str,
        session_id: str,
        run_id: str,
        turn_sequence: int,
        current_request: str,
        raw_messages: list[dict],
        raw_token_total: int,
        memory: dict,
        locked_constraints: list[str],
    ) -> dict:
        """Build one prompt-ready packet without changing canonical messages."""

        claude = self.claude_store.load(project_id, project_name)
        compaction = self._compaction_state(session_id, project_id)
        projected, counts = self.micro_compactor.compact(
            raw_messages,
            current_sequence=turn_sequence,
            current_request=current_request,
            locked_constraints=locked_constraints,
            project_id=project_id,
            session_id=session_id,
            run_id=run_id,
        )
        retrieved, retrieval_error = self._retrieve(project_id, current_request)
        core = {
            "claude_md": claude["content"],
            "memory": memory,
            "messages": projected,
            "retrieved_memories": retrieved,
        }
        usage = self.budget.usage(core)
        auto_requested = self.budget.should_auto_compact(raw_token_total, turn_sequence)
        if compaction["circuit_state"] == "open":
            auto_requested = False
        packet = {
            **core,
            "claude_meta": {key: value for key, value in claude.items() if "content" not in key},
            "budget": {
                **usage,
                "raw_conversation_tokens": raw_token_total,
                "auto_compact_threshold": self.budget.auto_compact_ratio,
            },
            "layers": {
                "artifact_offload": {
                    "status": "active",
                    "backend": self.blob_store.name,
                    "inline_char_limit": self.offloader.inline_char_limit,
                },
                "snip": {"status": "active", **counts},
                "micro_compact": {
                    "status": "active",
                    "full_turns": self.micro_compactor.full_turns,
                    "micro_turns": self.micro_compactor.micro_turns,
                    "half_life_turns": self.micro_compactor.half_life_turns,
                },
                "context_collapse": {
                    "status": "active",
                    "mode": "per-agent read projection",
                },
                "auto_compact": {
                    "status": "requested" if auto_requested else compaction["circuit_state"],
                    "requested": auto_requested,
                    "consecutive_failures": compaction["consecutive_failures"],
                    "circuit_state": compaction["circuit_state"],
                },
            },
            "compaction": {
                **compaction,
                "requested": auto_requested,
            },
            "retrieval": {
                "backend": self.vector_store.name,
                "embedding_backend": self.embedding_provider.name,
                "count": len(retrieved),
                "error": retrieval_error,
            },
        }
        self._save_packet(session_id, project_id, packet)
        return packet

    def project_for_agent(self, state: dict, agent: str) -> dict:
        return self.projector.project(state, agent)

    def memory_succeeded(self, state: dict, memory: dict) -> dict:
        """Commit managed CLAUDE.md, optional full snapshot and vector memory."""

        project_id = state["project_id"]
        session_id = state["session_id"]
        project_name = str(state.get("project_name") or "ArtFlow 项目")
        claude = self.claude_store.update_managed(project_id, project_name, memory)
        self._index_memory(state, memory)
        packet = dict(state.get("context_packet") or {})
        packet["claude_md"] = claude["content"]
        packet["claude_meta"] = {
            key: value for key, value in claude.items() if "content" not in key
        }
        if bool(packet.get("compaction", {}).get("requested")):
            try:
                self._save_snapshot(state, memory, claude["hash"])
                compact_status = {
                    "status": "completed",
                    "requested": True,
                    "consecutive_failures": 0,
                    "circuit_state": "closed",
                }
            except Exception as exc:
                # Snapshot validation/storage is part of Auto-compact. It uses
                # the same three-strike breaker and must not kill image work.
                failed = self.memory_failed(state, exc)
                compact_status = {
                    "status": "open" if failed["circuit_state"] == "open" else "failed",
                    "requested": True,
                    "consecutive_failures": failed["consecutive_failures"],
                    "circuit_state": failed["circuit_state"],
                }
            packet.setdefault("layers", {}).setdefault("auto_compact", {}).update(
                compact_status
            )
            packet["compaction"] = {
                **self._compaction_state(session_id, project_id),
                "requested": True,
            }
        self._save_packet(session_id, project_id, packet)
        return packet

    def memory_failed(self, state: dict, error: Exception) -> dict:
        """Count an Auto-compact failure and open the breaker at three."""

        session_id = state["session_id"]
        project_id = state["project_id"]
        timestamp = _now()
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT * FROM context_compactions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            failures = min(3, int(current["consecutive_failures"] if current else 0) + 1)
            circuit = "open" if failures >= 3 else "closed"
            connection.execute(
                """INSERT INTO context_compactions
                (session_id, project_id, consecutive_failures, circuit_state,
                 last_error, last_attempt_at, snapshot_version, last_packet_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, '{}', ?)
                ON CONFLICT(session_id) DO UPDATE SET
                consecutive_failures = excluded.consecutive_failures,
                circuit_state = excluded.circuit_state,
                last_error = excluded.last_error,
                last_attempt_at = excluded.last_attempt_at,
                updated_at = excluded.updated_at""",
                (
                    session_id,
                    project_id,
                    failures,
                    circuit,
                    str(error)[:1000],
                    timestamp,
                    timestamp,
                ),
            )
        return self._compaction_state(session_id, project_id)

    def reset_compaction_breaker(self, session_id: str) -> dict:
        timestamp = _now()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT project_id FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                raise KeyError(session_id)
            project_id = str(row["project_id"])
            connection.execute(
                """INSERT INTO context_compactions
                (session_id, project_id, consecutive_failures, circuit_state,
                 last_error, snapshot_version, last_packet_json, updated_at)
                VALUES (?, ?, 0, 'closed', '', 0, '{}', ?)
                ON CONFLICT(session_id) DO UPDATE SET consecutive_failures = 0,
                circuit_state = 'closed', last_error = '', updated_at = excluded.updated_at""",
                (session_id, project_id, timestamp),
            )
        return self._compaction_state(session_id, project_id)

    def get_status(self, project_id: str, session_id: str | None, project_name: str) -> dict:
        claude = self.claude_store.load(project_id, project_name)
        if session_id is None:
            return {
                "claude": {key: value for key, value in claude.items() if key != "content"},
                "claude_preview": claude["project_content"][:1200],
                "compaction": None,
                "layers": {},
                "storage": self.storage_status(),
            }
        state = self._compaction_state(session_id, project_id)
        with self.database.connect() as connection:
            artifact_count = int(connection.execute(
                "SELECT COUNT(*) FROM context_artifacts WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0])
            memory_count = int(connection.execute(
                "SELECT COUNT(*) FROM memory_items WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0])
        packet = state.pop("last_packet", {})
        return {
            "claude": {key: value for key, value in claude.items() if key not in {"content", "project_content"}},
            "claude_preview": claude["project_content"][:1200],
            "compaction": state,
            "layers": packet.get("layers", {}),
            "budget": packet.get("budget", {}),
            "retrieval": packet.get("retrieval", {}),
            "artifact_count": artifact_count,
            "memory_item_count": memory_count,
            "storage": self.storage_status(),
        }

    def replace_claude(self, project_id: str, project_name: str, content: str) -> dict:
        return self.claude_store.replace(project_id, project_name, content)

    def storage_status(self) -> dict:
        return {
            "blob": {"backend": self.blob_store.name},
            "vector": {"backend": self.vector_store.name},
            "embedding": {
                "backend": self.embedding_provider.name,
                "dimension": self.embedding_provider.dimension,
            },
        }

    def health(self) -> dict:
        return {
            "blob": self.blob_store.health(),
            "vector": self.vector_store.health(),
            "embedding": self.embedding_provider.health(),
        }

    def _compaction_state(self, session_id: str, project_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM context_compactions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                timestamp = _now()
                connection.execute(
                    """INSERT INTO context_compactions
                    (session_id, project_id, consecutive_failures, circuit_state,
                     last_error, snapshot_version, last_packet_json, updated_at)
                    VALUES (?, ?, 0, 'closed', '', 0, '{}', ?)""",
                    (session_id, project_id, timestamp),
                )
                return {
                    "consecutive_failures": 0,
                    "circuit_state": "closed",
                    "last_error": "",
                    "last_attempt_at": None,
                    "last_success_at": None,
                    "snapshot_version": 0,
                    "last_packet": {},
                }
        return {
            "consecutive_failures": int(row["consecutive_failures"]),
            "circuit_state": str(row["circuit_state"]),
            "last_error": str(row["last_error"] or ""),
            "last_attempt_at": row["last_attempt_at"],
            "last_success_at": row["last_success_at"],
            "snapshot_version": int(row["snapshot_version"]),
            "last_packet": json.loads(row["last_packet_json"] or "{}"),
        }

    def _save_packet(self, session_id: str, project_id: str, packet: dict) -> None:
        # Do not duplicate prompt content in SQLite. The status payload contains
        # layer metrics only; canonical context remains in its original stores.
        status_packet = {
            "budget": packet.get("budget", {}),
            "layers": packet.get("layers", {}),
            "retrieval": packet.get("retrieval", {}),
        }
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO context_compactions
                (session_id, project_id, consecutive_failures, circuit_state,
                 last_error, snapshot_version, last_packet_json, updated_at)
                VALUES (?, ?, 0, 'closed', '', 0, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET last_packet_json = excluded.last_packet_json,
                updated_at = excluded.updated_at""",
                (session_id, project_id, json.dumps(status_packet, ensure_ascii=False), timestamp),
            )

    def _save_snapshot(self, state: dict, memory: dict, claude_hash: str) -> None:
        missing = [key for key in MEMORY_KEYS if key not in memory]
        if missing:
            raise ValueError(f"auto-compact snapshot missing fields: {', '.join(missing)}")
        session_id = state["session_id"]
        project_id = state["project_id"]
        current = self._compaction_state(session_id, project_id)
        version = int(current["snapshot_version"]) + 1
        packet = state.get("context_packet") or {}
        token_before = int(packet.get("budget", {}).get("raw_conversation_tokens", 0))
        token_after = estimate_tokens(memory)
        timestamp = _now()
        with self.database.connect() as connection:
            source_count = int(connection.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0])
            connection.execute(
                """INSERT INTO memory_snapshots
                (id, session_id, project_id, version, summary_json, claude_md_hash,
                 source_message_count, token_before, token_after, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"snapshot_{uuid.uuid4().hex[:16]}",
                    session_id,
                    project_id,
                    version,
                    json.dumps(memory, ensure_ascii=False),
                    claude_hash,
                    source_count,
                    token_before,
                    token_after,
                    timestamp,
                ),
            )
            connection.execute(
                """UPDATE context_compactions SET consecutive_failures = 0,
                circuit_state = 'closed', last_error = '', last_success_at = ?,
                snapshot_version = ?, updated_at = ? WHERE session_id = ?""",
                (timestamp, version, timestamp, session_id),
            )

    def _index_memory(self, state: dict, memory: dict) -> None:
        rows: list[tuple[str, str, float]] = []
        importance_by_type = {
            "locked_constraints": 1.0,
            "project_goal": 0.95,
            "active_image": 0.9,
            "open_questions": 0.85,
            "rejected_directions": 0.8,
        }
        for memory_type, value in memory.items():
            values = value if isinstance(value, list) else [value]
            for item in values:
                if item in (None, "", {}, []):
                    continue
                content = (
                    json.dumps(item, ensure_ascii=False, sort_keys=True)
                    if isinstance(item, (dict, list))
                    else str(item)
                )
                rows.append((memory_type, content[:8000], importance_by_type.get(memory_type, 0.65)))
        if not rows:
            return
        project_id = state["project_id"]
        session_id = state["session_id"]
        turn_id = state.get("turn_id")
        timestamp = _now()
        records: list[VectorRecord] = []
        try:
            embeddings = self.embedding_provider.embed_documents([content for _, content, _ in rows])
            for (memory_type, content, importance), embedding in zip(rows, embeddings, strict=True):
                digest = hashlib.sha256(
                    f"{project_id}:{memory_type}:{content}".encode("utf-8")
                ).hexdigest()
                memory_id = f"mem_{digest[:24]}"
                records.append(
                    VectorRecord(
                        id=memory_id,
                        project_id=project_id,
                        session_id=session_id,
                        memory_type=memory_type,
                        content=content,
                        importance=importance,
                        embedding=embedding,
                    )
                )
            self.vector_store.upsert(records)
            embedding_status = "indexed"
        except Exception:
            records = []
            embedding_status = "failed"
        with self.database.connect() as connection:
            for memory_type, content, importance in rows:
                digest = hashlib.sha256(
                    f"{project_id}:{memory_type}:{content}".encode("utf-8")
                ).hexdigest()
                memory_id = f"mem_{digest[:24]}"
                connection.execute(
                    """INSERT INTO memory_items
                    (id, project_id, session_id, source_turn_id, memory_type, content,
                     importance, embedding_status, vector_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET importance = excluded.importance,
                    embedding_status = excluded.embedding_status, vector_id = excluded.vector_id,
                    updated_at = excluded.updated_at""",
                    (
                        memory_id,
                        project_id,
                        session_id,
                        turn_id,
                        memory_type,
                        content,
                        importance,
                        embedding_status,
                        memory_id if embedding_status == "indexed" else None,
                        timestamp,
                        timestamp,
                    ),
                )

    def _retrieve(self, project_id: str, query: str) -> tuple[list[dict], str]:
        if not query or self.semantic_top_k <= 0:
            return [], ""
        try:
            embedding = self.embedding_provider.embed_query(query)
            return self.vector_store.search(
                embedding,
                project_id=project_id,
                limit=self.semantic_top_k,
            ), ""
        except Exception as exc:
            # Retrieval must never block the creative pipeline. The complete
            # source-of-truth remains available in SQLite/CLAUDE.md.
            return [], type(exc).__name__
