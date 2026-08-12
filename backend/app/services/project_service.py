from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.database import Database
from app.image_backends.base import GeneratedImage
from app.schemas.image_request import CanvasSnapshotRequest

if TYPE_CHECKING:
    from app.context import ContextEngine


DEFAULT_PROJECT_ID = "project_default"
DEFAULT_SESSION_ID = "session_default"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def decode_json(value: str | None, fallback):
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return fallback


class ProjectService:
    def __init__(
        self,
        database: Database,
        assets_dir: Path,
        images_dir: Path,
        context_recent_messages: int = 16,
        context_max_tokens: int = 12000,
        context_engine: ContextEngine | None = None,
    ) -> None:
        self.database = database
        self.assets_dir = assets_dir
        self.images_dir = images_dir
        self.context_recent_messages = max(4, context_recent_messages)
        self.context_max_tokens = max(1000, context_max_tokens)
        self.context_engine = context_engine

    def ensure_default_project(self) -> None:
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM projects WHERE id = ?", (DEFAULT_PROJECT_ID,)
            ).fetchone()
            if existing:
                return

            timestamp = now_iso()
            prompt = (
                "设计一个地下炼金术师 Boss，四条机械手臂，阴暗神秘，"
                "适合像素游戏转化"
            )
            world = "地下炼金实验室，古老仪式与机械融合"
            reference_name = "reference-seed.png"
            reference_source = self.assets_dir / "candidate-D.png"
            reference_destination = self.images_dir.parent / "uploads" / reference_name
            reference_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(reference_source, reference_destination)

            connection.execute(
                """INSERT INTO projects
                (id, name, user_request, world_context, aspect_ratio, image_count,
                 reference_images, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    DEFAULT_PROJECT_ID,
                    "地下炼金术师",
                    prompt,
                    world,
                    "1:1",
                    4,
                    json.dumps([f"/storage/uploads/{reference_name}"]),
                    "completed",
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                "INSERT INTO sessions (id, project_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (DEFAULT_SESSION_ID, DEFAULT_PROJECT_ID, "首次创作", timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    f"msg_{uuid.uuid4().hex[:10]}",
                    DEFAULT_SESSION_ID,
                    "assistant",
                    "你好，我是 ArtFlow 助手。我会协调多个专业 Agent，为你打造最合适的游戏美术方案。",
                    timestamp,
                ),
            )
            run_id = "run_seed"
            connection.execute(
                "INSERT INTO agent_runs (id, project_id, status, backend, started_at, completed_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, DEFAULT_PROJECT_ID, "completed", "mock", timestamp, timestamp),
            )
            images = self._copy_seed_images(run_id, prompt)
            self._insert_images(connection, DEFAULT_PROJECT_ID, run_id, images, timestamp)
            selected_id = images[0].id
            connection.execute(
                "UPDATE projects SET selected_image_id = ? WHERE id = ?",
                (selected_id, DEFAULT_PROJECT_ID),
            )
            self._insert_events(connection, DEFAULT_PROJECT_ID, run_id, timestamp)
            connection.execute(
                "INSERT INTO canvas_snapshots (id, project_id, selected_image_id, state_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    f"canvas_{uuid.uuid4().hex[:10]}",
                    DEFAULT_PROJECT_ID,
                    selected_id,
                    json.dumps({"selected_image_id": selected_id}),
                    timestamp,
                ),
            )

    def create_project(self, name: str) -> dict:
        project_id = f"project_{uuid.uuid4().hex[:12]}"
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        timestamp = now_iso()
        clean_name = name.strip()[:80] or "未命名对话"
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO projects
                (id, name, user_request, world_context, aspect_ratio, image_count,
                 reference_images, status, created_at, updated_at)
                VALUES (?, ?, '', '', '1:1', 4, '[]', 'ready', ?, ?)""",
                (project_id, clean_name, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO sessions (id, project_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, project_id, clean_name, timestamp, timestamp),
            )
        return self.get_project(project_id)

    def _copy_seed_images(self, run_id: str, prompt: str) -> list[GeneratedImage]:
        metadata = (
            ("A", "腐化炼金主宰", "约束忠实"),
            ("B", "秘仪炼金先驱", "大胆构图"),
            ("C", "熔炉炼金暴君", "清晰剪影"),
            ("D", "幽影炼金术师", "色彩氛围"),
        )
        self.images_dir.mkdir(parents=True, exist_ok=True)
        results: list[GeneratedImage] = []
        for index, (label, title, variation) in enumerate(metadata):
            image_id = f"img_seed_{label.lower()}"
            filename = f"{run_id}-{label.lower()}-{image_id}.png"
            destination = self.images_dir / filename
            shutil.copy2(self.assets_dir / f"candidate-{label}.png", destination)
            results.append(
                GeneratedImage(
                    id=image_id,
                    label=label,
                    title=title,
                    variation=variation,
                    file_path=str(destination),
                    public_url=f"/storage/images/{filename}",
                    prompt=prompt,
                    seed=86100 + index * 137,
                    width=1254,
                    height=1254,
                    model="phase1-curated-seed",
                    variant_key=("constraint", "composition", "silhouette", "palette")[index],
                    request_json={"source": "phase1_seed"},
                )
            )
        return results

    def _insert_images(
        self,
        connection,
        project_id: str,
        run_id: str,
        images: list[GeneratedImage],
        timestamp: str,
    ) -> None:
        connection.executemany(
            """INSERT INTO generated_images
            (id, project_id, run_id, label, title, variation, file_path, public_url,
             prompt, backend, model, negative_prompt, loras, variant_key, prompt_id,
             workflow_template, workflow_path, generation_params, seed, width, height,
             created_at, parent_image_id, source_turn_id, version_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    image.id,
                    project_id,
                    run_id,
                    image.label,
                    image.title,
                    image.variation,
                    image.file_path,
                    image.public_url,
                    image.prompt,
                    image.backend,
                    image.model,
                    image.negative_prompt,
                    json.dumps(image.loras, ensure_ascii=False),
                    image.variant_key,
                    image.prompt_id,
                    image.workflow_template,
                    image.workflow_path,
                    json.dumps(image.generation_params, ensure_ascii=False),
                    image.seed,
                    image.width,
                    image.height,
                    timestamp,
                    image.parent_image_id,
                    image.source_turn_id,
                    image.version_number,
                )
                for image in images
            ],
        )
        connection.executemany(
            """INSERT INTO generation_workflows
            (id, project_id, run_id, image_id, backend, prompt_id, variant_key,
             template_name, workflow_path, workflow_json, request_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    f"workflow_{image.id}",
                    project_id,
                    run_id,
                    image.id,
                    image.backend,
                    image.prompt_id,
                    image.variant_key,
                    image.workflow_template,
                    image.workflow_path,
                    json.dumps(image.workflow_json, ensure_ascii=False),
                    json.dumps(image.request_json, ensure_ascii=False),
                    timestamp,
                )
                for image in images
            ],
        )

    def _insert_events(
        self, connection, project_id: str, run_id: str, timestamp: str
    ) -> None:
        event_specs = (
            ("tasks_dispatched", "supervisor_agent", "prepare", "completed", 1, "Supervisor Agent", "已冻结上下文并派发 3 个隔离子任务。"),
            ("child_completed", "composition_agent", "isolated_task", "completed", 1, "Composition Agent", "构图与空间层次提案已返回。"),
            ("child_completed", "subject_agent", "isolated_task", "completed", 1, "Subject Agent", "角色、道具与轮廓提案已返回。"),
            ("child_completed", "style_agent", "isolated_task", "completed", 1, "Style Agent", "画风、色板与光照提案已返回。"),
            ("all_children_joined", "supervisor_agent", "waiting", "completed", 1, "Supervisor Agent", "并行屏障已收齐 3/3 个终态消息。"),
            ("agent_completed", "supervisor_agent", "aggregate", "completed", 1, "Supervisor Agent", "已审核并合并全部专业结果。"),
            ("image_completed", "image_agent", "generation", "completed", 1, "Image Agent", "4 张候选图已保存到本地并插入画布。"),
            ("agent_completed", "supervisor_agent", "finalize", "completed", 1, "Supervisor Agent", "本轮创作任务已完成。"),
        )
        rows = []
        for sequence, spec in enumerate(event_specs, start=1):
            event_type, agent, stage, status, attempt, title, summary = spec
            rows.append(
                (
                    f"evt_{uuid.uuid4().hex[:12]}",
                    project_id,
                    run_id,
                    event_type,
                    agent,
                    stage,
                    status,
                    attempt,
                    title,
                    summary,
                    "{}",
                    sequence,
                    timestamp,
                )
            )
        connection.executemany(
            """INSERT INTO agent_events
            (id, project_id, run_id, event_type, agent, stage, status, attempt,
             title, summary, payload, sequence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    def get_project(self, project_id: str = DEFAULT_PROJECT_ID) -> dict:
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if not project:
                raise KeyError(project_id)
            run = connection.execute(
                "SELECT * FROM agent_runs WHERE project_id = ? ORDER BY started_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            images = connection.execute(
                "SELECT * FROM generated_images WHERE project_id = ? ORDER BY version_number DESC, created_at DESC, label",
                (project_id,),
            ).fetchall()
            events = [] if run is None else connection.execute(
                "SELECT * FROM agent_events WHERE run_id = ? ORDER BY sequence",
                (run["id"],),
            ).fetchall()
            messages = connection.execute(
                """SELECT m.* FROM messages m
                JOIN sessions s ON s.id = m.session_id
                WHERE s.project_id = ? ORDER BY m.created_at""",
                (project_id,),
            ).fetchall()
            session = connection.execute(
                "SELECT * FROM sessions WHERE project_id = ? ORDER BY created_at LIMIT 1",
                (project_id,),
            ).fetchone()
            turns = [] if session is None else connection.execute(
                "SELECT * FROM conversation_turns WHERE session_id = ? ORDER BY sequence",
                (session["id"],),
            ).fetchall()
            memory = None if session is None else connection.execute(
                "SELECT * FROM conversation_memory WHERE session_id = ?",
                (session["id"],),
            ).fetchone()
            invocations = [] if run is None else connection.execute(
                "SELECT * FROM agent_invocations WHERE run_id = ? ORDER BY started_at, id",
                (run["id"],),
            ).fetchall()

        payload = {
            "project": {
                **dict(project),
                "reference_images": decode_json(project["reference_images"], []),
            },
            "run": dict(run) if run is not None else None,
            "session": dict(session) if session is not None else None,
            "images": [
                {
                    **dict(row),
                    "loras": decode_json(row["loras"], []),
                    "generation_params": decode_json(row["generation_params"], {}),
                }
                for row in images
            ],
            "events": [
                {**dict(row), "payload": decode_json(row["payload"], {})}
                for row in events
            ],
            "messages": [
                {
                    **dict(row),
                    "attachments": decode_json(row["attachments"], []),
                    "metadata": decode_json(row["metadata"], {}),
                }
                for row in messages
            ],
            "turns": [dict(row) for row in turns],
            "memory": {} if memory is None else decode_json(memory["summary_json"], {}),
            "memory_meta": None if memory is None else {
                "summarized_through_sequence": memory["summarized_through_sequence"],
                "source_message_count": memory["source_message_count"],
                "updated_at": memory["updated_at"],
            },
            "agent_invocations": [
                {**dict(row), "structured_output": decode_json(row["structured_output"], {})}
                for row in invocations
            ],
        }
        payload["context_status"] = (
            self.context_engine.get_status(
                project_id,
                str(session["id"]) if session is not None else None,
                str(project["name"]),
            )
            if self.context_engine is not None
            else None
        )
        return payload

    def get_recent_project(self) -> dict:
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT id FROM projects ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        if not project:
            raise KeyError("recent")
        return self.get_project(project["id"])

    def list_conversations(self) -> list[dict]:
        """Return lightweight local conversation summaries for the sidebar.

        A conversation is represented by one project and its single durable
        session. Full messages, images, Agent events and memory are loaded only
        after the user explicitly selects an item.
        """

        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT
                    s.id AS session_id,
                    s.project_id AS project_id,
                    CASE
                        WHEN s.title IN ('首次创作', '新创作') THEN p.name
                        ELSE s.title
                    END AS title,
                    s.created_at AS created_at,
                    s.updated_at AS updated_at,
                    p.status AS status,
                    COALESCE((
                        SELECT m.content FROM messages m
                        WHERE m.session_id = s.id
                        ORDER BY m.created_at DESC LIMIT 1
                    ), '') AS preview,
                    (SELECT COUNT(*) FROM conversation_turns t WHERE t.session_id = s.id) AS turn_count,
                    (SELECT COUNT(*) FROM generated_images i WHERE i.project_id = s.project_id) AS image_count
                FROM sessions s
                JOIN projects p ON p.id = s.project_id
                ORDER BY s.updated_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_conversation(self, session_id: str) -> dict:
        """Remove one conversation and move its generated files into local trash."""

        with self.database.connect() as connection:
            session = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not session:
                raise KeyError(session_id)
            project_id = str(session["project_id"])
            running = connection.execute(
                "SELECT id FROM agent_runs WHERE project_id = ? AND status = 'running' LIMIT 1",
                (project_id,),
            ).fetchone()
            if running:
                raise ValueError("当前对话仍在生成，请等待本轮结束后再删除")

            image_rows = connection.execute(
                "SELECT file_path, workflow_path FROM generated_images WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            run_rows = connection.execute(
                "SELECT id FROM agent_runs WHERE project_id = ?", (project_id,)
            ).fetchall()

            # Delete dependent rows explicitly. The schema intentionally avoids
            # cascade rules so every locally persisted artifact remains auditable.
            for table in (
                "generation_workflows",
                "agent_invocations",
                "agent_events",
                "agent_artifacts",
                "memory_vectors",
                "memory_items",
                "memory_snapshots",
                "context_artifacts",
                "context_compactions",
                "project_context_files",
                "canvas_snapshots",
                "generated_images",
                "conversation_memory",
                "messages",
                "conversation_turns",
                "style_profiles",
                "agent_runs",
            ):
                key = (
                    "session_id"
                    if table in {"conversation_memory", "messages", "context_compactions"}
                    else "project_id"
                )
                value = session_id if key == "session_id" else project_id
                connection.execute(f"DELETE FROM {table} WHERE {key} = ?", (value,))
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))

        trash_dir = self.images_dir.parent / "trash" / f"{session_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        storage_root = self.images_dir.parent.resolve()
        file_paths = {
            str(value)
            for row in image_rows
            for value in (row["file_path"], row["workflow_path"])
            if value
        }
        file_paths.update(
            str(self.images_dir.parent / "logs" / f"{row['id']}.jsonl")
            for row in run_rows
        )
        moved = 0
        for raw_path in file_paths:
            path = Path(raw_path)
            try:
                resolved = path.resolve()
                if not resolved.is_file() or not resolved.is_relative_to(storage_root):
                    continue
                trash_dir.mkdir(parents=True, exist_ok=True)
                destination = trash_dir / f"{moved:03d}-{resolved.name}"
                shutil.move(str(resolved), destination)
                moved += 1
            except OSError:
                # Database deletion already succeeded. A locked file may safely
                # remain in storage and can be cleaned up manually later.
                continue
        return {"session_id": session_id, "project_id": project_id, "trashed_files": moved}

    def create_conversation_turn(
        self,
        *,
        project_id: str,
        prompt: str,
        world_context: str,
        aspect_ratio: str,
        reference_images: list[str],
        style_profile: dict,
        image_backend: str,
        image_model: str,
    ) -> tuple[str, str, dict]:
        """Create one durable conversation turn and its isolated LangGraph run."""

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        turn_id = f"turn_{uuid.uuid4().hex[:12]}"
        message_id = f"msg_{uuid.uuid4().hex[:10]}"
        timestamp = now_iso()
        with self.database.connect() as connection:
            session = connection.execute(
                "SELECT * FROM sessions WHERE project_id = ? ORDER BY created_at LIMIT 1",
                (project_id,),
            ).fetchone()
            project = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if not session or not project:
                raise KeyError(project_id)
            sequence = int(connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM conversation_turns WHERE session_id = ?",
                (session["id"],),
            ).fetchone()[0])
            image_count = 4 if sequence == 1 else 2
            version_number = int(connection.execute(
                "SELECT COALESCE(MAX(version_number), 0) + 1 FROM generated_images WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0])
            parent_image = None
            if sequence > 1 and project["selected_image_id"]:
                parent_image = connection.execute(
                    "SELECT * FROM generated_images WHERE id = ?", (project["selected_image_id"],)
                ).fetchone()
            attachments = list(reference_images)
            connection.execute(
                """INSERT INTO agent_runs
                (id, project_id, status, backend, checkpoint_thread_id, started_at, session_id, turn_id)
                VALUES (?, ?, 'running', ?, ?, ?, ?, ?)""",
                (run_id, project_id, f"langgraph+{image_backend}", run_id, timestamp, session["id"], turn_id),
            )
            connection.execute(
                """INSERT INTO conversation_turns
                (id, session_id, project_id, run_id, sequence, status, user_message_id,
                 parent_image_id, requested_count, created_at)
                VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)""",
                (turn_id, session["id"], project_id, run_id, sequence, message_id, project["selected_image_id"], image_count, timestamp),
            )
            connection.execute(
                """INSERT INTO messages
                (id, session_id, role, content, turn_id, attachments, metadata, token_estimate, created_at)
                VALUES (?, ?, 'user', ?, ?, ?, '{}', ?, ?)""",
                (message_id, session["id"], prompt, turn_id, json.dumps(attachments), max(1, len(prompt) // 4), timestamp),
            )
            connection.execute(
                """UPDATE projects SET user_request = ?, world_context = ?, aspect_ratio = ?,
                image_count = ?, reference_images = ?, status = 'generating', updated_at = ? WHERE id = ?""",
                (prompt, world_context, aspect_ratio, image_count, json.dumps(attachments), timestamp, project_id),
            )
            connection.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (timestamp, session["id"]))
            recent = connection.execute(
                """SELECT m.id, m.role, m.content, m.turn_id, m.created_at,
                COALESCE(t.sequence, 0) AS turn_sequence
                FROM messages m
                LEFT JOIN conversation_turns t ON t.id = m.turn_id
                WHERE m.session_id = ? ORDER BY m.created_at DESC LIMIT ?""",
                (session["id"], self.context_recent_messages * 2),
            ).fetchall()
            memory_row = connection.execute(
                "SELECT * FROM conversation_memory WHERE session_id = ?", (session["id"],)
            ).fetchone()
            token_total = int(connection.execute(
                "SELECT COALESCE(SUM(token_estimate), 0) FROM messages WHERE session_id = ?",
                (session["id"],),
            ).fetchone()[0])

        memory = {} if memory_row is None else decode_json(memory_row["summary_json"], {})
        locked = list(memory.get("locked_constraints") or [])
        parent_payload = {} if parent_image is None else dict(parent_image)
        recent_messages = [dict(row) for row in reversed(recent)]
        context_packet = (
            self.context_engine.prepare_packet(
                project_id=project_id,
                project_name=str(project["name"]),
                session_id=str(session["id"]),
                run_id=run_id,
                turn_sequence=sequence,
                current_request=prompt,
                raw_messages=recent_messages,
                raw_token_total=token_total,
                memory=memory,
                locked_constraints=locked,
            )
            if self.context_engine is not None
            else {}
        )
        initial_state = {
            "thread_id": run_id,
            "run_id": run_id,
            "project_id": project_id,
            "project_name": str(project["name"]),
            "session_id": session["id"],
            "turn_id": turn_id,
            "turn_sequence": sequence,
            "version_number": version_number,
            "user_request": prompt,
            "reference_images": attachments,
            "world_context": world_context,
            "aspect_ratio": aspect_ratio,
            "image_count": image_count,
            "style_profile": style_profile,
            "image_backend": image_backend,
            "image_model": image_model,
            "parent_image": parent_payload,
            "recent_messages": recent_messages,
            "context_packet": context_packet,
            "memory": memory,
            "locked_constraints": locked,
            "compress_context": (
                bool(context_packet.get("compaction", {}).get("requested"))
                if context_packet
                else sequence % 10 == 0 or token_total > self.context_max_tokens
            ),
            "proposals": [],
            "reviews": [],
            "events": [],
            "attempts": {},
            "candidate_images": [],
            "status": "briefing",
        }
        return run_id, turn_id, initial_state

    # Compatibility wrapper for older API/tests. New code should create a turn.
    def create_agent_run(
        self, project_id: str, prompt: str, world_context: str, aspect_ratio: str,
        image_count: int, reference_images: list[str], style_profile: dict, image_backend: str,
    ) -> tuple[str, dict]:
        del image_count
        run_id, _, state = self.create_conversation_turn(
            project_id=project_id, prompt=prompt, world_context=world_context,
            aspect_ratio=aspect_ratio, reference_images=reference_images,
            style_profile=style_profile, image_backend=image_backend,
            image_model="qwen-image-2.0" if image_backend == "qwen_image" else style_profile.get("style_bible", {}).get("generation", {}).get("base_model", "mock"),
        )
        return run_id, state

    def complete_agent_run(self, run_id: str, state: dict) -> None:
        completed_at = now_iso()
        with self.database.connect() as connection:
            run = connection.execute(
                "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if not run:
                raise KeyError(run_id)
            project_id = run["project_id"]
            session = connection.execute(
                "SELECT id FROM sessions WHERE project_id = ? ORDER BY created_at LIMIT 1",
                (project_id,),
            ).fetchone()
            images = [GeneratedImage(**image) for image in state.get("candidate_images", [])]
            self._insert_images(connection, project_id, run_id, images, completed_at)
            project = connection.execute(
                "SELECT selected_image_id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            selected_id = images[0].id if images else (project["selected_image_id"] if project else None)
            result = {
                "constraints": state.get("constraints", {}),
                "style_bible": state.get("style_bible", {}),
                "selected_concept": state.get("selected_concept", {}),
                "attempts": state.get("attempts", {}),
                "style_profile": state.get("style_profile", {}),
                "workflow_request": state.get("workflow_request", {}),
                "routing": state.get("routing", {}),
                "memory": state.get("memory", {}),
            }
            connection.execute(
                """UPDATE agent_runs
                SET status = 'completed', result_json = ?, completed_at = ?
                WHERE id = ?""",
                (json.dumps(result, ensure_ascii=False), completed_at, run_id),
            )
            connection.execute(
                """UPDATE projects SET selected_image_id = ?, status = 'completed',
                updated_at = ? WHERE id = ?""",
                (selected_id, completed_at, project_id),
            )
            if session:
                assistant_message_id = f"msg_{uuid.uuid4().hex[:10]}"
                assistant_message = state.get("assistant_message") or (
                    f"Agent 工作流已完成，生成 {len(images)} 张候选图。"
                    if images else "本轮讨论已完成。"
                )
                connection.execute(
                    """INSERT INTO messages
                    (id, session_id, role, content, turn_id, attachments, metadata,
                     token_estimate, created_at)
                    VALUES (?, ?, 'assistant', ?, ?, '[]', ?, ?, ?)""",
                    (
                        assistant_message_id,
                        session["id"],
                        assistant_message,
                        run["turn_id"],
                        json.dumps({"generated_image_ids": [image.id for image in images]}, ensure_ascii=False),
                        max(1, len(assistant_message) // 4),
                        completed_at,
                    ),
                )
                if run["turn_id"]:
                    connection.execute(
                        """UPDATE conversation_turns SET status = 'completed', route = ?,
                        assistant_message_id = ?, completed_at = ? WHERE id = ?""",
                        (state.get("routing", {}).get("route", "generate"), assistant_message_id, completed_at, run["turn_id"]),
                    )
                memory = state.get("memory", {})
                turn_sequence = int(state.get("turn_sequence", 0))
                message_count = int(connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session["id"],)
                ).fetchone()[0])
                connection.execute(
                    """INSERT INTO conversation_memory
                    (session_id, project_id, summary_json, summarized_through_sequence,
                     source_message_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET summary_json = excluded.summary_json,
                    summarized_through_sequence = excluded.summarized_through_sequence,
                    source_message_count = excluded.source_message_count, updated_at = excluded.updated_at""",
                    (session["id"], project_id, json.dumps(memory, ensure_ascii=False), turn_sequence, message_count, completed_at),
                )
                if state.get("context_was_compressed"):
                    connection.execute(
                        "UPDATE messages SET included_in_summary = 1 WHERE session_id = ? AND turn_id != ?",
                        (session["id"], run["turn_id"]),
                    )
                connection.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (completed_at, session["id"]))

    def fail_agent_run(self, run_id: str, error: str) -> None:
        timestamp = now_iso()
        with self.database.connect() as connection:
            run = connection.execute(
                "SELECT project_id, turn_id FROM agent_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if not run:
                return
            connection.execute(
                """UPDATE agent_runs SET status = 'failed', error = ?, completed_at = ?
                WHERE id = ?""",
                (error[:2000], timestamp, run_id),
            )
            connection.execute(
                "UPDATE projects SET status = 'failed', updated_at = ? WHERE id = ?",
                (timestamp, run["project_id"]),
            )
            if run["turn_id"]:
                connection.execute(
                    "UPDATE conversation_turns SET status = 'failed', completed_at = ? WHERE id = ?",
                    (timestamp, run["turn_id"]),
                )

    def prepare_retry(self, run_id: str) -> str:
        timestamp = now_iso()
        with self.database.connect() as connection:
            run = connection.execute(
                "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if not run:
                raise KeyError(run_id)
            if run["status"] != "failed":
                raise ValueError("only failed runs can be retried")
            connection.execute(
                """UPDATE agent_runs SET status = 'running', error = NULL,
                completed_at = NULL, retry_count = retry_count + 1 WHERE id = ?""",
                (run_id,),
            )
            connection.execute(
                "UPDATE projects SET status = 'generating', updated_at = ? WHERE id = ?",
                (timestamp, run["project_id"]),
            )
        return str(run["project_id"])

    def get_run(self, run_id: str) -> dict:
        with self.database.connect() as connection:
            run = connection.execute(
                "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if not run:
            raise KeyError(run_id)
        return {**dict(run), "result_json": decode_json(run["result_json"], {})}

    def get_turn(self, turn_id: str) -> dict:
        with self.database.connect() as connection:
            turn = connection.execute(
                "SELECT * FROM conversation_turns WHERE id = ?", (turn_id,)
            ).fetchone()
            if not turn:
                raise KeyError(turn_id)
            messages = connection.execute(
                "SELECT * FROM messages WHERE turn_id = ? ORDER BY created_at", (turn_id,)
            ).fetchall()
            images = connection.execute(
                "SELECT * FROM generated_images WHERE source_turn_id = ? ORDER BY label", (turn_id,)
            ).fetchall()
        return {
            "turn": dict(turn),
            "messages": [{**dict(row), "attachments": decode_json(row["attachments"], []), "metadata": decode_json(row["metadata"], {})} for row in messages],
            "images": [{**dict(row), "loras": decode_json(row["loras"], []), "generation_params": decode_json(row["generation_params"], {})} for row in images],
        }

    def get_image_metadata(self, image_id: str) -> dict:
        with self.database.connect() as connection:
            image = connection.execute(
                "SELECT * FROM generated_images WHERE id = ?", (image_id,)
            ).fetchone()
            workflow = connection.execute(
                "SELECT * FROM generation_workflows WHERE image_id = ?", (image_id,)
            ).fetchone()
        if not image:
            raise KeyError(image_id)
        payload = {
            **dict(image),
            "loras": decode_json(image["loras"], []),
            "generation_params": decode_json(image["generation_params"], {}),
        }
        payload["workflow"] = None if workflow is None else {
            **dict(workflow),
            "workflow_json": decode_json(workflow["workflow_json"], {}),
            "request_json": decode_json(workflow["request_json"], {}),
        }
        return payload

    def save_canvas(self, project_id: str, snapshot: CanvasSnapshotRequest) -> dict:
        timestamp = now_iso()
        with self.database.connect() as connection:
            exists = connection.execute(
                "SELECT id FROM generated_images WHERE id = ? AND project_id = ?",
                (snapshot.selected_image_id, project_id),
            ).fetchone()
            if not exists:
                raise KeyError(snapshot.selected_image_id)
            connection.execute(
                "UPDATE projects SET selected_image_id = ?, updated_at = ? WHERE id = ?",
                (snapshot.selected_image_id, timestamp, project_id),
            )
            connection.execute(
                "INSERT INTO canvas_snapshots (id, project_id, selected_image_id, state_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    f"canvas_{uuid.uuid4().hex[:10]}",
                    project_id,
                    snapshot.selected_image_id,
                    snapshot.model_dump_json(),
                    timestamp,
                ),
            )
        return {"ok": True, "selected_image_id": snapshot.selected_image_id}
