from pydantic import BaseModel, Field

from app.schemas.image_request import LoRAConfig


class GenerationStyle(BaseModel):
    base_model: str
    steps: int = Field(default=28, ge=1, le=150)
    cfg: float = Field(default=4.5, ge=0, le=30)
    sampler_name: str = "euler"
    scheduler: str = "normal"
    loras: list[LoRAConfig] = Field(default_factory=list, max_length=4)


class StyleProfileData(BaseModel):
    visual: dict
    generation: GenerationStyle


class StyleProfile(BaseModel):
    id: str
    project_id: str
    name: str
    style_bible: StyleProfileData
