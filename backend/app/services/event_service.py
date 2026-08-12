import json
import uuid
from datetime import UTC, datetime

from app.database import Database


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class EventService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def append(self, project_id: str, run_id: str, events: list[dict]) -> None:
        if not events:
            return
        with self.database.connect() as connection:
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM agent_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            rows = []
            for event in events:
                sequence += 1
                rows.append(
                    (
                        event["id"],
                        project_id,
                        run_id,
                        event["event_type"],
                        event["agent"],
                        event["stage"],
                        event["status"],
                        int(event.get("attempt", 1)),
                        event["title"],
                        event["summary"],
                        json.dumps(event.get("payload", {}), ensure_ascii=False),
                        sequence,
                        event.get("created_at", now_iso()),
                    )
                )
            connection.executemany(
                """INSERT OR IGNORE INTO agent_events
                (id, project_id, run_id, event_type, agent, stage, status, attempt,
                 title, summary, payload, sequence, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )

    def append_artifacts(self, project_id: str, run_id: str, update: dict) -> None:
        artifacts: list[tuple] = []
        timestamp = now_iso()
        for proposal in update.get("proposals", []):
            # 5-Agent协议使用task_id关联父子任务；兼容旧proposal_id，且避免
            # 非关键的artifact归档字段缺失导致整条图像生成链路失败。
            proposal_id = (
                proposal.get("proposal_id")
                or proposal.get("task_id")
                or f"proposal_{uuid.uuid4().hex[:12]}"
            )
            artifacts.append(
                (
                    proposal_id,
                    project_id,
                    run_id,
                    proposal.get("agent", "unknown_agent"),
                    "proposal",
                    int(proposal.get("attempt", 1)),
                    json.dumps(proposal, ensure_ascii=False),
                    timestamp,
                )
            )
        for review in update.get("reviews", []):
            artifact_id = review.get("review_id") or f"review_{uuid.uuid4().hex[:12]}"
            artifacts.append(
                (
                    artifact_id,
                    project_id,
                    run_id,
                    "supervisor_agent",
                    "review",
                    int(review.get("attempt", 1)),
                    json.dumps(review, ensure_ascii=False),
                    timestamp,
                )
            )
        if not artifacts:
            return
        with self.database.connect() as connection:
            connection.executemany(
                """INSERT OR IGNORE INTO agent_artifacts
                (id, project_id, run_id, agent, artifact_type, attempt, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                artifacts,
            )

    def list_after(self, run_id: str, sequence: int) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM agent_events
                WHERE run_id = ? AND sequence > ? ORDER BY sequence""",
                (run_id, sequence),
            ).fetchall()
        return [
            {**dict(row), "payload": json.loads(row["payload"] or "{}")}
            for row in rows
        ]

    def run_status(self, run_id: str) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT status FROM agent_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return None if row is None else str(row["status"])
