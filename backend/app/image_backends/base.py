from dataclasses import dataclass, field
from typing import Protocol

from app.schemas.image_request import ImageGenerationRequest


@dataclass(slots=True)
class GeneratedImage:
    id: str
    label: str
    title: str
    variation: str
    file_path: str
    public_url: str
    prompt: str
    seed: int
    width: int = 1024
    height: int = 1024
    backend: str = "mock"
    model: str = ""
    negative_prompt: str = ""
    loras: list[dict] = field(default_factory=list)
    variant_key: str = "constraint"
    prompt_id: str | None = None
    workflow_template: str | None = None
    workflow_path: str | None = None
    workflow_json: dict = field(default_factory=dict)
    request_json: dict = field(default_factory=dict)
    generation_params: dict = field(default_factory=dict)
    parent_image_id: str | None = None
    source_turn_id: str | None = None
    version_number: int = 1


class ImageBackend(Protocol):
    name: str

    async def health(self) -> dict: ...

    async def generate(
        self, request: ImageGenerationRequest
    ) -> list[GeneratedImage]: ...
