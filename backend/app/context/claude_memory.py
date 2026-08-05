"""Hierarchical ``CLAUDE.md`` loader and safe auto-maintainer.

The repository-level file is read-only application guidance. Each art project
gets its own file; the Memory Agent may rewrite only the managed block, so user
notes outside that block survive automatic updates.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from app.database import Database


AUTO_BEGIN = "<!-- ARTFLOW:AUTO-MEMORY:BEGIN -->"
AUTO_END = "<!-- ARTFLOW:AUTO-MEMORY:END -->"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ClaudeMemoryStore:
    def __init__(self, database: Database, root: Path, global_file: Path) -> None:
        self.database = database
        self.root = root.resolve()
        self.global_file = global_file.resolve()

    def _project_dir(self, project_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", project_id)
        return self.root / safe_id

    def _path(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "CLAUDE.md"

    def _default(self, project_name: str) -> str:
        return (
            f"# {project_name} · ArtFlow Project Memory\n\n"
            "此文件会在每轮 Memory Agent 成功后自动更新。你可以在托管区块外追加长期说明。\n\n"
            f"{AUTO_BEGIN}\n"
            "## 当前项目记忆\n\n尚未形成结构化记忆。\n"
            f"{AUTO_END}\n\n"
            "## 用户长期备注\n\n- 可在此处添加不希望 Agent 自动改写的要求。\n"
        )

    def ensure(self, project_id: str, project_name: str) -> Path:
        path = self._path(project_id)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(path, self._default(project_name))
            self._record(project_id, path, 1)
        return path

    def load(self, project_id: str, project_name: str) -> dict:
        path = self.ensure(project_id, project_name)
        project_content = path.read_text(encoding="utf-8")
        global_content = (
            self.global_file.read_text(encoding="utf-8") if self.global_file.exists() else ""
        )
        combined = (
            "# ArtFlow 全局记忆\n\n"
            f"{global_content.strip()}\n\n"
            "# 当前项目记忆\n\n"
            f"{project_content.strip()}\n"
        )
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT version FROM project_context_files WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return {
            "content": combined,
            "project_content": project_content,
            "path": str(path),
            "hash": _hash(combined),
            "project_hash": _hash(project_content),
            "version": int(row["version"]) if row else 1,
            "auto_managed": True,
        }

    def update_managed(self, project_id: str, project_name: str, memory: dict) -> dict:
        path = self.ensure(project_id, project_name)
        current = path.read_text(encoding="utf-8")
        rendered = self._render(memory)
        if AUTO_BEGIN in current and AUTO_END in current:
            before, remainder = current.split(AUTO_BEGIN, 1)
            _, after = remainder.split(AUTO_END, 1)
            updated = f"{before}{AUTO_BEGIN}\n{rendered}\n{AUTO_END}{after}"
        else:
            updated = f"{current.rstrip()}\n\n{AUTO_BEGIN}\n{rendered}\n{AUTO_END}\n"
        if updated != current:
            version = self._next_version(project_id)
            self._archive(path, current, version - 1)
            self._atomic_write(path, updated)
            self._record(project_id, path, version)
        return self.load(project_id, project_name)

    def replace(self, project_id: str, project_name: str, content: str) -> dict:
        if len(content) > 50_000:
            raise ValueError("CLAUDE.md 不能超过 50,000 个字符")
        path = self.ensure(project_id, project_name)
        current = path.read_text(encoding="utf-8")
        version = self._next_version(project_id)
        self._archive(path, current, version - 1)
        self._atomic_write(path, content.rstrip() + "\n")
        self._record(project_id, path, version)
        return self.load(project_id, project_name)

    def _render(self, memory: dict) -> str:
        labels = {
            "project_goal": "项目目标",
            "locked_constraints": "锁定约束",
            "style_decisions": "风格决定",
            "character_facts": "角色事实",
            "composition_facts": "构图事实",
            "rejected_directions": "已否决方向",
            "active_image": "当前父图",
            "open_questions": "待确认问题",
        }
        lines = ["## Memory Agent 自动维护区", ""]
        for key, label in labels.items():
            value = memory.get(key)
            lines.append(f"### {label}")
            if value in (None, "", [], {}):
                lines.append("- 暂无")
            elif isinstance(value, list):
                lines.extend(f"- {str(item)[:1000]}" for item in value[:30])
            elif isinstance(value, dict):
                lines.append("```json")
                lines.append(json.dumps(value, ensure_ascii=False, indent=2)[:6000])
                lines.append("```")
            else:
                lines.append(str(value)[:3000])
            lines.append("")
        lines.append(f"> 自动更新时间：{_now()}")
        return "\n".join(lines).rstrip()

    def _next_version(self, project_id: str) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT version FROM project_context_files WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return (int(row["version"]) if row else 0) + 1

    def _record(self, project_id: str, path: Path, version: int) -> None:
        content = path.read_text(encoding="utf-8")
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO project_context_files
                (project_id, file_path, content_hash, version, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET file_path = excluded.file_path,
                content_hash = excluded.content_hash, version = excluded.version,
                updated_at = excluded.updated_at""",
                (project_id, str(path), _hash(content), version, _now()),
            )

    def _archive(self, path: Path, content: str, version: int) -> None:
        history = path.parent / "history"
        history.mkdir(parents=True, exist_ok=True)
        archive = history / f"CLAUDE.v{max(1, version):04d}.md"
        if not archive.exists():
            archive.write_text(content, encoding="utf-8")

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_suffix(".md.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
