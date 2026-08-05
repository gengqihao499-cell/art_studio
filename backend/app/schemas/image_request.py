from typing import Literal

from pydantic import BaseModel, Field, model_validator


class LoRAConfig(BaseModel):
    id: str
    filename: str
    weight: float = Field(default=0.75, ge=0, le=2)
    trigger_word: str = ""


class CandidateVariant(BaseModel):
    key: Literal["constraint", "composition", "silhouette", "palette"]
    label: Literal["A", "B", "C", "D"]
    title: str
    variation: str
    prompt_suffix: str
    seed_offset: int = 0
    cfg_delta: float = 0


class ImageGenerationRequest(BaseModel):
    project_id: str
    run_id: str
    backend: Literal["mock", "comfyui", "qwen_image"] = "mock"
    base_model: str
    positive_prompt: str
    negative_prompt: str = ""
    width: int = Field(default=1024, ge=256, le=4096, multiple_of=8)
    height: int = Field(default=1024, ge=256, le=4096, multiple_of=8)
    batch_size: int = Field(default=1, ge=1, le=4)
    steps: int = Field(default=28, ge=1, le=150)
    cfg: float = Field(default=4.5, ge=0, le=30)
    seed: int = Field(default=1, ge=0)
    sampler_name: str = "euler"
    scheduler: str = "normal"
    reference_images: list[str] = Field(default_factory=list, max_length=5)
    parent_image_id: str | None = None
    source_turn_id: str | None = None
    version_number: int = Field(default=1, ge=1)
    generation_mode: Literal["create", "edit"] = "create"
    loras: list[LoRAConfig] = Field(default_factory=list, max_length=4)
    variants: list[CandidateVariant] = Field(min_length=1, max_length=4)
    workflow_template: str = "txt2img_core_v1"

    @model_validator(mode="after")
    def unique_variants(self):
        if len({variant.key for variant in self.variants}) != len(self.variants):
            raise ValueError("candidate variant keys must be unique")
        return self


class CanvasSnapshotRequest(BaseModel):
    selected_image_id: str


class NewProjectRequest(BaseModel):
    name: str = "未命名项目"
