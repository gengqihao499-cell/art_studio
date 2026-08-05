"""Qwen Image 2.0 generation/edit adapter for Alibaba Cloud Beijing."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.image_backends.base import GeneratedImage
from app.providers.base import ProviderError
from app.schemas.image_request import CandidateVariant, ImageGenerationRequest


def _find_image_urls(payload: object) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"url", "image", "image_url"} and isinstance(value, str) and value.startswith("http"):
                found.append(value)
            else:
                found.extend(_find_image_urls(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_find_image_urls(item))
    return list(dict.fromkeys(found))


class QwenImageBackend:
    """Issue one request per controlled variant with bounded concurrency."""

    name = "qwen_image"

    def __init__(
        self,
        *,
        api_key: str,
        workspace_id: str,
        api_host: str = "",
        images_dir: Path,
        storage_dir: Path,
        model: str = "qwen-image-2.0",
        timeout_seconds: float = 180,
        max_concurrency: int = 2,
        prompt_extend: bool = True,
        watermark: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key or (not workspace_id and not api_host):
            raise RuntimeError("Qwen Image 需要 API Key 以及 Workspace ID 或 API Host")
        self.model = model
        self.images_dir = images_dir
        self.storage_dir = storage_dir
        self.prompt_extend = prompt_extend
        self.watermark = watermark
        self._api_key = api_key
        base_url = api_host.strip().rstrip("/") or f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com"
        self._url = f"{base_url}/api/v1/services/aigc/multimodal-generation/generation"
        self._semaphore = asyncio.Semaphore(max(1, min(max_concurrency, 4)))
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True)
        self._owns_client = client is None

    async def health(self) -> dict:
        return {
            "available": True,
            "configured": True,
            "region": "cn-beijing",
            "model": self.model,
            "mode": "Qwen Image generation + editing",
            "api_host": self._url.split("/api/v1/", 1)[0],
        }

    def _reference_content(self, reference: str) -> dict | None:
        if reference.startswith(("http://", "https://", "data:")):
            return {"image": reference}
        path = Path(reference)
        if reference.startswith("/storage/"):
            path = self.storage_dir / reference.removeprefix("/storage/")
        if not path.is_file():
            return None
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {"image": f"data:{mime};base64,{encoded}"}

    async def _generate_variant(
        self,
        request: ImageGenerationRequest,
        variant: CandidateVariant,
        index: int,
    ) -> GeneratedImage:
        prompt = f"{request.positive_prompt}, {variant.prompt_suffix}".strip(", ")
        content: list[dict] = []
        if request.generation_mode == "edit":
            for reference in request.reference_images[:3]:
                item = await asyncio.to_thread(self._reference_content, reference)
                if item:
                    content.append(item)
        content.append({"text": prompt})
        payload = {
            "model": self.model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": {
                "n": 1,
                "size": f"{request.width}*{request.height}",
                "prompt_extend": self.prompt_extend,
                "watermark": self.watermark,
            },
        }
        async with self._semaphore:
            try:
                response = await self._client.post(
                    self._url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "X-DashScope-DataInspection": "enable",
                    },
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                request_id = exc.response.headers.get("x-request-id", "")
                suffix = f"，request_id={request_id}" if request_id else ""
                raise ProviderError(f"千问图像请求失败（HTTP {exc.response.status_code}）{suffix}") from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"无法连接千问图像服务：{type(exc).__name__}") from exc

        response_payload = response.json()
        urls = _find_image_urls(response_payload)
        if not urls:
            message = response_payload.get("message") if isinstance(response_payload, dict) else None
            raise ProviderError(f"千问图像响应中没有图片地址：{message or 'unknown response'}")
        source_url = urls[0]
        download = await self._client.get(source_url)
        download.raise_for_status()
        suffix = Path(urlparse(source_url).path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".png"
        image_id = f"img_{uuid.uuid4().hex[:12]}"
        filename = f"{request.run_id}-{variant.label.lower()}-{image_id}{suffix}"
        destination = self.images_dir / filename
        self.images_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(destination.write_bytes, download.content)
        request_id = response.headers.get("x-request-id") or response_payload.get("request_id")
        return GeneratedImage(
            id=image_id,
            label=variant.label,
            title=variant.title,
            variation=variant.variation,
            file_path=str(destination),
            public_url=f"/storage/images/{filename}",
            prompt=prompt,
            seed=request.seed + variant.seed_offset + index,
            width=request.width,
            height=request.height,
            backend=self.name,
            model=self.model,
            negative_prompt=request.negative_prompt,
            variant_key=variant.key,
            prompt_id=str(request_id or ""),
            request_json={
                "model": self.model,
                "generation_mode": request.generation_mode,
                "size": f"{request.width}*{request.height}",
                "variant": variant.model_dump(),
            },
            generation_params={"prompt_extend": self.prompt_extend, "watermark": self.watermark},
            parent_image_id=request.parent_image_id,
            source_turn_id=request.source_turn_id,
            version_number=request.version_number,
        )

    async def generate(self, request: ImageGenerationRequest) -> list[GeneratedImage]:
        return await asyncio.gather(
            *(self._generate_variant(request, variant, index) for index, variant in enumerate(request.variants))
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
