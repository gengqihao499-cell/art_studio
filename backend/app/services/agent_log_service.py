"""Persistent, redacted per-Agent execution logs.

Each invocation is stored in SQLite for the right-side inspector and mirrored to a
JSONL audit file. Prompts are summarized before persistence; credentials are never
accepted by this service and therefore cannot be logged accidentally.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.database import Database
from app.providers.base import ChatResult

if TYPE_CHECKING:
    from app.context.artifact_offloader import ArtifactOffloader


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _summary(value: str, limit: int = 420) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else normalized[:limit] + "…"


class AgentLogService:
    def __init__(
        self,
        database: Database,
        logs_dir: Path,
        artifact_offloader: ArtifactOffloader | None = None,
    ) -> None:
        self.database = database
        self.logs_dir = logs_dir
        self.artifact_offloader = artifact_offloader

    def record(
        self,
        *,
        state: dict,
        agent: str,
        status: str,
        model: str,
        input_text: str,
        output_text: str = "",
        structured_output: dict | None = None,
        result: ChatResult | None = None,
        attempt: int = 1,
        reason: str = "",
        error: str = "",
    ) -> dict:
        invocation_id = f"inv_{uuid.uuid4().hex[:12]}"
        started_at = _now()
        stored_output = structured_output or {}
        if self.artifact_offloader and structured_output:
            reference = self.artifact_offloader.offload_json(
                structured_output,
                project_id=state["project_id"],
                session_id=state.get("session_id") or "session_unknown",
                run_id=state.get("run_id"),
                artifact_type="agent_structured_output",
            )
            if reference:
                stored_output = {"artifact": reference, "offloaded": True}
        row = {
            "id": invocation_id,
            "project_id": state["project_id"],
            "session_id": state.get("session_id"),
            "turn_id": state.get("turn_id"),
            "run_id": state["run_id"],
            "agent": agent,
            "status": status,
            "attempt": attempt,
            "model": model,
            "reason": _summary(reason),
            "input_summary": _summary(input_text),
            "output_summary": _summary(output_text),
            "structured_output": stored_output,
            "latency_ms": result.latency_ms if result else 0,
            "input_tokens": result.input_tokens if result else 0,
            "output_tokens": result.output_tokens if result else 0,
            "error_code": type(error).__name__ if isinstance(error, Exception) else "",
            "error_message": _summary(str(error)),
            "started_at": started_at,
            "completed_at": _now(),
        }
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO agent_invocations
                (id, project_id, session_id, turn_id, run_id, agent, status, attempt,
                 model, reason, input_summary, output_summary, structured_output,
                 latency_ms, input_tokens, output_tokens, error_code, error_message,
                 started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["id"], row["project_id"], row["session_id"], row["turn_id"],
                    row["run_id"], row["agent"], row["status"], row["attempt"],
                    row["model"], row["reason"], row["input_summary"], row["output_summary"],
                    json.dumps(row["structured_output"], ensure_ascii=False),
                    row["latency_ms"], row["input_tokens"], row["output_tokens"],
                    row["error_code"], row["error_message"], row["started_at"], row["completed_at"],
                ),
            )
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        with (self.logs_dir / f"{state['run_id']}.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def list_for_run(self, run_id: str) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_invocations WHERE run_id = ? ORDER BY started_at, id",
                (run_id,),
            ).fetchall()
        return [
            {**dict(row), "structured_output": json.loads(row["structured_output"] or "{}")}
            for row in rows
        ]
