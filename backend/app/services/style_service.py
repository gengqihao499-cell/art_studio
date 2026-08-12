"""风格配置服务。

负责为项目创建、读取和持久化默认 Style Profile。这里保存的是所有 Agent
和图像后端都必须遵守的硬风格契约，不负责调用大模型或生成图片。
"""

import json
from datetime import UTC, datetime

from app.database import Database
from app.schemas.style import GenerationStyle, StyleProfile, StyleProfileData


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class StyleService:
    """管理项目级风格配置，并兼容已经落盘的旧项目。"""

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
        """确保项目存在默认风格，并返回可直接放入 Agent 状态的字典。"""

        # 保留旧 ID，确保用户已有项目无需数据库迁移也能原位更新风格内容。
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
                # 键名是稳定的程序接口，值使用中文并为关键视觉术语保留英文括注。
                visual={
                    "style_name": "原创横版沙盒像素风",
                    "rendering_medium": (
                        "清晰的2D像素画（crisp 2D pixel art），"
                        "明显的方形像素簇，硬边缘，最近邻缩放效果"
                    ),
                    "camera": (
                        "正交横版侧视角（orthographic side view），"
                        "不使用透视汇聚和等距视角"
                    ),
                    "pixel_rule": (
                        "统一像素密度，不使用抗锯齿、柔和渐变和亚像素细节"
                    ),
                    "shape_language": (
                        "模块化图格地形、清晰剪影、块状建筑结构；"
                        "仅在用户明确要求时加入角色"
                    ),
                    "palette_rule": (
                        "有限且鲜明的色板，每个生物群系使用独立色系，"
                        "采用4至6级阶梯式明度"
                    ),
                    "lighting_rule": (
                        "阶梯式像素阴影、少量发光像素簇，禁止柔光和体积光"
                    ),
                    "materials": [
                        "泥土与草地图格",
                        "岩石和矿石簇",
                        "木制平台",
                        "像素植被",
                        "发光晶体",
                    ],
                    "readability_rule": (
                        "前景、中景和背景层次清楚；"
                        "所有可见对象在原生精灵尺寸下仍可辨认"
                    ),
                    "forbidden": [
                        "写实摄影",
                        "3D渲染",
                        "平滑数字厚涂",
                        "柔和喷枪阴影",
                        "抗锯齿边缘",
                        "等距视角",
                        "写实人体比例",
                        "游戏Logo",
                        "复制参考图角色",
                        "复制参考图UI",
                        "复制现有游戏素材或标志性角色",
                    ],
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
                    "原创横版沙盒像素风",
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
            name="原创横版沙盒像素风",
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
