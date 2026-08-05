import json
from datetime import UTC, datetime

from app.database import Database
from app.schemas.style import GenerationStyle, StyleProfile, StyleProfileData


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class StyleService:
    def __init__(
        self,
        database: Database,
        default_model: str,
        default_lora: str = "",
    ) -> None:
        self.database = database
        self.default_model = default_model
        self.default_lora = default_lora

    def ensure_default(self, project_id: str) -> dict:
        profile_id = f"style_{project_id}_dark_alchemy"
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT style_profile_id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if not project:
                raise KeyError(project_id)
            if project["style_profile_id"]:
                row = connection.execute(
                    "SELECT * FROM style_profiles WHERE id = ?",
                    (project["style_profile_id"],),
                ).fetchone()
                if row and row["id"] != profile_id:
                    return self._decode(row)

            timestamp = now_iso()
            loras = []
            if self.default_lora:
                loras.append(
                    {
                        "id": "dark_alchemy_v1",
                        "filename": self.default_lora,
                        "weight": 0.75,
                        "trigger_word": "s86b5p",
                    }
                )
            data = StyleProfileData(
                visual={
                    "mood": "dark underground alchemy",
                    "shape_language": "heavy robe, radial mechanical arms, compact apparatus",
                    "materials": ["blackened iron", "aged bronze", "worn cloth", "glass"],
                    "palette_rule": "cold dark environment, one warm alchemy focal point",
                    "readability_rule": "full silhouette and at least three value layers",
                },
                generation=GenerationStyle(
                    base_model=self.default_model,
                    steps=28,
                    cfg=4.5,
                    sampler_name="euler",
                    scheduler="normal",
                    loras=loras,
                ),
            )
            connection.execute(
                """INSERT INTO style_profiles
                (id, project_id, name, style_bible, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    style_bible = excluded.style_bible,
                    updated_at = excluded.updated_at""",
                (
                    profile_id,
                    project_id,
                    "暗黑炼金 · 游戏概念",
                    data.model_dump_json(),
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE projects SET style_profile_id = ? WHERE id = ?",
                (profile_id, project_id),
            )
        return StyleProfile(
            id=profile_id,
            project_id=project_id,
            name="暗黑炼金 · 游戏概念",
            style_bible=data,
        ).model_dump()

    def get_selected(self, project_id: str) -> dict:
        return self.ensure_default(project_id)

    def list_for_project(self, project_id: str) -> list[dict]:
        self.ensure_default(project_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM style_profiles WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    @staticmethod
    def _decode(row) -> dict:
        return StyleProfile(
            id=row["id"],
            project_id=row["project_id"],
            name=row["name"],
            style_bible=json.loads(row["style_bible"]),
        ).model_dump()
