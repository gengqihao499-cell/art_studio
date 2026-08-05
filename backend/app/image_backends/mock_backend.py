import asyncio
import hashlib
import shutil
import uuid
from pathlib import Path

from app.image_backends.base import GeneratedImage
from app.schemas.image_request import ImageGenerationRequest


class MockImageBackend:
    """Local deterministic adapter used when no ComfyUI service is configured."""

    name = "mock"

    def __init__(self, assets_dir: Path, images_dir: Path) -> None:
        self.assets_dir = assets_dir
        self.images_dir = images_dir

    async def health(self) -> dict:
        return {"available": True, "mode": "local curated candidates"}

    async def generate(
        self, request: ImageGenerationRequest
    ) -> list[GeneratedImage]:
        self.images_dir.mkdir(parents=True, exist_ok=True)
        results: list[GeneratedImage] = []

        for index, variant in enumerate(request.variants):
            source = self.assets_dir / f"candidate-{variant.label}.png"
            image_id = f"img_{uuid.uuid4().hex[:12]}"
            filename = f"{request.run_id}-{variant.label.lower()}-{image_id}.png"
            destination = self.images_dir / filename
            await asyncio.to_thread(shutil.copy2, source, destination)
            prompt = f"{request.positive_prompt}, {variant.prompt_suffix}"
            digest = hashlib.sha256(
                f"{prompt}:{request.run_id}:{index}".encode("utf-8")
            ).hexdigest()
            seed = request.seed + variant.seed_offset + int(digest[:4], 16)
            params = {
                "steps": request.steps,
                "cfg": round(request.cfg + variant.cfg_delta, 2),
                "sampler_name": request.sampler_name,
                "scheduler": request.scheduler,
            }
            results.append(
                GeneratedImage(
                    id=image_id,
                    label=variant.label,
                    title=variant.title,
                    variation=variant.variation,
                    file_path=str(destination),
                    public_url=f"/storage/images/{filename}",
                    prompt=prompt,
                    seed=seed,
                    width=request.width,
                    height=request.height,
                    backend=self.name,
                    model=request.base_model,
                    negative_prompt=request.negative_prompt,
                    loras=[lora.model_dump() for lora in request.loras],
                    variant_key=variant.key,
                    workflow_template=request.workflow_template,
                    request_json=request.model_dump(),
                    generation_params=params,
                    parent_image_id=request.parent_image_id,
                    source_turn_id=request.source_turn_id,
                    version_number=request.version_number,
                )
            )

        await asyncio.sleep(0.35)
        return results
