import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    user_request TEXT NOT NULL DEFAULT '',
    world_context TEXT NOT NULL DEFAULT '',
    aspect_ratio TEXT NOT NULL DEFAULT '1:1',
    image_count INTEGER NOT NULL DEFAULT 4,
    reference_images TEXT NOT NULL DEFAULT '[]',
    style_profile_id TEXT,
    selected_image_id TEXT,
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    turn_id TEXT,
    attachments TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    token_estimate INTEGER NOT NULL DEFAULT 0,
    included_in_summary INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    run_id TEXT,
    sequence INTEGER NOT NULL,
    route TEXT NOT NULL DEFAULT 'generate',
    status TEXT NOT NULL DEFAULT 'running',
    user_message_id TEXT,
    assistant_message_id TEXT,
    parent_image_id TEXT,
    requested_count INTEGER NOT NULL DEFAULT 4,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS conversation_memory (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    summary_json TEXT NOT NULL DEFAULT '{}',
    summarized_through_sequence INTEGER NOT NULL DEFAULT 0,
    source_message_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    status TEXT NOT NULL,
    backend TEXT NOT NULL,
    checkpoint_thread_id TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    session_id TEXT,
    turn_id TEXT
);

CREATE TABLE IF NOT EXISTS agent_invocations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    session_id TEXT,
    turn_id TEXT,
    run_id TEXT NOT NULL REFERENCES agent_runs(id),
    agent TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    model TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    input_summary TEXT NOT NULL DEFAULT '',
    output_summary TEXT NOT NULL DEFAULT '',
    structured_output TEXT NOT NULL DEFAULT '{}',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    run_id TEXT NOT NULL REFERENCES agent_runs(id),
    event_type TEXT NOT NULL,
    agent TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    sequence INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generated_images (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    run_id TEXT NOT NULL REFERENCES agent_runs(id),
    label TEXT NOT NULL,
    title TEXT NOT NULL,
    variation TEXT NOT NULL,
    file_path TEXT NOT NULL,
    public_url TEXT NOT NULL,
    prompt TEXT NOT NULL,
    backend TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    loras TEXT NOT NULL DEFAULT '[]',
    variant_key TEXT NOT NULL DEFAULT '',
    prompt_id TEXT,
    workflow_template TEXT,
    workflow_path TEXT,
    generation_params TEXT NOT NULL DEFAULT '{}',
    seed INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    parent_image_id TEXT,
    source_turn_id TEXT,
    version_number INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS canvas_snapshots (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    selected_image_id TEXT,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS style_profiles (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    style_bible TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    run_id TEXT NOT NULL REFERENCES agent_runs(id),
    agent TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generation_workflows (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    run_id TEXT NOT NULL REFERENCES agent_runs(id),
    image_id TEXT NOT NULL REFERENCES generated_images(id),
    backend TEXT NOT NULL,
    prompt_id TEXT,
    variant_key TEXT NOT NULL,
    template_name TEXT,
    workflow_path TEXT,
    workflow_json TEXT NOT NULL DEFAULT '{}',
    request_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- Context Engine tables are deliberately separate from conversation_memory.
-- conversation_memory remains the current working summary; these tables keep
-- immutable snapshots, offloaded artifacts and circuit-breaker state.
CREATE TABLE IF NOT EXISTS context_artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    session_id TEXT REFERENCES sessions(id),
    run_id TEXT,
    artifact_type TEXT NOT NULL,
    storage_backend TEXT NOT NULL,
    uri TEXT NOT NULL,
    preview TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    content_type TEXT NOT NULL DEFAULT 'application/json',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_snapshots (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    version INTEGER NOT NULL,
    summary_json TEXT NOT NULL,
    claude_md_hash TEXT NOT NULL DEFAULT '',
    source_message_count INTEGER NOT NULL DEFAULT 0,
    token_before INTEGER NOT NULL DEFAULT 0,
    token_after INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, version)
);

CREATE TABLE IF NOT EXISTS context_compactions (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    circuit_state TEXT NOT NULL DEFAULT 'closed',
    last_error TEXT NOT NULL DEFAULT '',
    last_attempt_at TEXT,
    last_success_at TEXT,
    snapshot_version INTEGER NOT NULL DEFAULT 0,
    last_packet_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_context_files (
    project_id TEXT PRIMARY KEY REFERENCES projects(id),
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    session_id TEXT NOT NULL REFERENCES sessions(id),
    source_turn_id TEXT,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 0.5,
    embedding_status TEXT NOT NULL DEFAULT 'pending',
    vector_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_vectors (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 0.5,
    embedding_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_project ON agent_runs(project_id, started_at);
CREATE INDEX IF NOT EXISTS idx_events_run ON agent_events(run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_images_run ON generated_images(run_id, label);
CREATE INDEX IF NOT EXISTS idx_snapshots_project ON canvas_snapshots(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON agent_artifacts(run_id, agent, attempt);
CREATE INDEX IF NOT EXISTS idx_workflows_run ON generation_workflows(run_id, variant_key);
CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns(session_id, sequence);
CREATE INDEX IF NOT EXISTS idx_invocations_run ON agent_invocations(run_id, started_at);
CREATE INDEX IF NOT EXISTS idx_context_artifacts_session ON context_artifacts(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_snapshots_session ON memory_snapshots(session_id, version);
CREATE INDEX IF NOT EXISTS idx_memory_items_project ON memory_items(project_id, memory_type, updated_at);
CREATE INDEX IF NOT EXISTS idx_memory_vectors_project ON memory_vectors(project_id, memory_type);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._ensure_column(connection, "agent_runs", "checkpoint_thread_id", "TEXT")
            self._ensure_column(
                connection, "agent_runs", "result_json", "TEXT NOT NULL DEFAULT '{}'"
            )
            self._ensure_column(connection, "agent_runs", "error", "TEXT")
            self._ensure_column(
                connection, "agent_runs", "retry_count", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(connection, "agent_runs", "session_id", "TEXT")
            self._ensure_column(connection, "agent_runs", "turn_id", "TEXT")
            self._ensure_column(connection, "projects", "style_profile_id", "TEXT")
            for column, definition in (
                ("turn_id", "TEXT"),
                ("attachments", "TEXT NOT NULL DEFAULT '[]'"),
                ("metadata", "TEXT NOT NULL DEFAULT '{}'"),
                ("token_estimate", "INTEGER NOT NULL DEFAULT 0"),
                ("included_in_summary", "INTEGER NOT NULL DEFAULT 0"),
            ):
                self._ensure_column(connection, "messages", column, definition)
            for column, definition in (
                ("model", "TEXT NOT NULL DEFAULT ''"),
                ("negative_prompt", "TEXT NOT NULL DEFAULT ''"),
                ("loras", "TEXT NOT NULL DEFAULT '[]'"),
                ("variant_key", "TEXT NOT NULL DEFAULT ''"),
                ("prompt_id", "TEXT"),
                ("workflow_template", "TEXT"),
                ("workflow_path", "TEXT"),
                ("generation_params", "TEXT NOT NULL DEFAULT '{}'"),
                ("parent_image_id", "TEXT"),
                ("source_turn_id", "TEXT"),
                ("version_number", "INTEGER NOT NULL DEFAULT 1"),
            ):
                self._ensure_column(connection, "generated_images", column, definition)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_images_project_version ON generated_images(project_id, version_number, created_at)"
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )
