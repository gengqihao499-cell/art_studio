import asyncio
import json
import mimetypes
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.image_backends.base import GeneratedImage
from app.image_backends.comfyui_workflow import WorkflowTemplateCompiler
from app.schemas.image_request import CandidateVariant, ImageGenerationRequest


class ComfyUIError(RuntimeError):
    pass


class ComfyUIImageBackend:
    name = "comfyui"

    def __init__(
        self,
        base_url: str,
        images_dir: Path,
        workflows_dir: Path,
        storage_dir: Path,
        template_path: Path,
        timeout_seconds: float = 300,
        poll_interval: float = 0.5,
        api_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.images_dir = images_dir
        self.workflows_dir = workflows_dir
        self.storage_dir = storage_dir.resolve()
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self.api_key = api_key
        self.transport = transport
        self.compiler = WorkflowTemplateCompiler(template_path)

    def _client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=30,
            transport=self.transport,
        )

    async def health(self) -> dict:
        try:
            async with self._client() as client:
                response = await client.get("/system_stats", timeout=2)
                response.raise_for_status()
                return {"available": True, "base_url": self.base_url}
        except httpx.HTTPError as exc:
            return {
                "available": False,
                "base_url": self.base_url,
                "error": str(exc),
            }

    async def generate(
        self, request: ImageGenerationRequest
    ) -> list[GeneratedImage]:
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        client_id = uuid.uuid4().hex
        async with self._client() as client:
            uploaded_references = await self._upload_references(client, request)
            tasks = [
                self._run_variant(client, client_id, request, variant, uploaded_references)
                for variant in request.variants
            ]
            return list(await asyncio.gather(*tasks))

    async def _run_variant(
        self,
        client: httpx.AsyncClient,
        client_id: str,
        request: ImageGenerationRequest,
        variant: CandidateVariant,
        uploaded_references: list[dict],
    ) -> GeneratedImage:
        prompt_id = uuid.uuid4().hex
        output_prefix = f"ArtFlow/{request.run_id}/{variant.label}"
        workflow = self.compiler.compile(
            request, variant, output_prefix, uploaded_references
        )
        workflow_path = self.workflows_dir / f"{request.run_id}-{variant.key}.json"
        workflow_path.write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        response = await client.post(
            "/prompt",
            json={"prompt": workflow, "client_id": client_id, "prompt_id": prompt_id},
        )
        response.raise_for_status()
        payload = response.json()
        submitted_id = payload.get("prompt_id", prompt_id)
        if payload.get("error") or not submitted_id:
            raise ComfyUIError(
                f"ComfyUI rejected workflow: {payload.get('error') or payload}"
            )
        output = await self._wait_for_output(client, str(submitted_id))
        image_response = await client.get(
            "/view",
            params={
                "filename": output["filename"],
                "subfolder": output.get("subfolder", ""),
                "type": output.get("type", "output"),
            },
            follow_redirects=True,
        )
        image_response.raise_for_status()
        image_id = f"img_{uuid.uuid4().hex[:12]}"
        suffix = Path(output["filename"]).suffix.lower() or ".png"
        filename = f"{request.run_id}-{variant.label.lower()}-{image_id}{suffix}"
        destination = self.images_dir / filename
        destination.write_bytes(image_response.content)
        prompt = f"{request.positive_prompt}, {variant.prompt_suffix}"
        params = {
            "steps": request.steps,
            "cfg": round(request.cfg + variant.cfg_delta, 2),
            "sampler_name": request.sampler_name,
            "scheduler": request.scheduler,
            "uploaded_references": uploaded_references,
        }
        return GeneratedImage(
            id=image_id,
            label=variant.label,
            title=variant.title,
            variation=variant.variation,
            file_path=str(destination),
            public_url=f"/storage/images/{filename}",
            prompt=prompt,
            seed=request.seed + variant.seed_offset,
            width=request.width,
            height=request.height,
            backend=self.name,
            model=request.base_model,
            negative_prompt=request.negative_prompt,
            loras=[lora.model_dump() for lora in request.loras],
            variant_key=variant.key,
            prompt_id=str(submitted_id),
            workflow_template=self.compiler.name,
            workflow_path=str(workflow_path),
            workflow_json=workflow,
            request_json=request.model_dump(),
            generation_params=params,
            parent_image_id=request.parent_image_id,
            source_turn_id=request.source_turn_id,
            version_number=request.version_number,
        )

    async def _wait_for_output(self, client: httpx.AsyncClient, prompt_id: str) -> dict:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            response = await client.get(f"/history/{prompt_id}")
            response.raise_for_status()
            history = response.json().get(prompt_id)
            if history:
                for node_output in history.get("outputs", {}).values():
                    images = node_output.get("images", [])
                    if images:
                        return images[0]
                status = history.get("status", {})
                if status.get("status_str") in {"error", "failed"}:
                    raise ComfyUIError(f"ComfyUI execution failed: {status}")
            await asyncio.sleep(self.poll_interval)
        raise ComfyUIError(f"ComfyUI timed out after {self.timeout_seconds:g}s")

    async def _upload_references(
        self, client: httpx.AsyncClient, request: ImageGenerationRequest
    ) -> list[dict]:
        uploaded: list[dict] = []
        for reference in request.reference_images:
            path = self._resolve_reference(reference)
            if path is None:
                continue
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            headers = {key: value for key, value in client.headers.items() if key.lower() != "content-type"}
            response = await client.post(
                "/upload/image",
                headers=headers,
                files={"image": (path.name, path.read_bytes(), mime)},
                data={"type": "input", "overwrite": "true"},
            )
            response.raise_for_status()
            uploaded.append(response.json())
        return uploaded

    def _resolve_reference(self, reference: str) -> Path | None:
        parsed = urlparse(reference)
        path_value = parsed.path if parsed.scheme else reference
        if path_value.startswith("/storage/"):
            candidate = (self.storage_dir / path_value.removeprefix("/storage/")).resolve()
        else:
            candidate = Path(path_value).resolve()
        if candidate != self.storage_dir and self.storage_dir not in candidate.parents:
            return None
        return candidate if candidate.is_file() else None
