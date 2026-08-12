"""阿里云万相 2.7 微调 LoRA 图像后端。

部署后的万相 LoRA 只支持异步调用：先创建生成任务，再轮询任务状态，最后把
临时图片 URL 下载到 ArtFlow 的本地存储。本文件只负责供应商协议适配，不参与
Agent 决策、提示词编排或上下文管理。
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.image_backends.base import GeneratedImage
from app.providers.base import ProviderError
from app.schemas.image_request import CandidateVariant, ImageGenerationRequest


TERMINAL_FAILURE_STATES = {"FAILED", "CANCELED", "UNKNOWN"}


def _find_image_urls(payload: object) -> list[str]:
    """兼容同步/异步响应结构，递归提取所有远程图片地址。"""

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


class WanLoraImageBackend:
    """调用已部署且状态为 RUNNING 的万相 2.7 LoRA 模型。"""

    name = "wan_lora"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        images_dir: Path,
        storage_dir: Path,
        trigger_word: str = "",
        api_host: str = "https://dashscope.aliyuncs.com",
        timeout_seconds: float = 600,
        poll_interval_seconds: float = 1.5,
        max_concurrency: int = 2,
        watermark: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("万相 LoRA 后端缺少 DASHSCOPE_API_KEY")
        if not model:
            raise RuntimeError("万相 LoRA 后端缺少 WAN_DEPLOYED_MODEL（填写 deployed_model，不是 job_id）")

        self.model = model
        self.images_dir = images_dir
        self.storage_dir = storage_dir
        self.trigger_word = trigger_word.strip().strip(",")
        self.timeout_seconds = max(30.0, timeout_seconds)
        self.poll_interval_seconds = max(0.05, poll_interval_seconds)
        self.watermark = watermark
        self._api_key = api_key
        self._base_url = api_host.strip().rstrip("/") or "https://dashscope.aliyuncs.com"
        self._create_url = f"{self._base_url}/api/v1/services/aigc/image-generation/generation"
        self._semaphore = asyncio.Semaphore(max(1, min(max_concurrency, 4)))
        self._client = client or httpx.AsyncClient(timeout=min(self.timeout_seconds, 90), follow_redirects=True)
        self._owns_client = client is None

    async def health(self) -> dict:
        """返回静态配置状态；真实可用性以生成任务结果为准。"""

        return {
            "available": True,
            "configured": True,
            "region": "cn-beijing",
            "model": self.model,
            "mode": "Wan 2.7 deployed LoRA (async generation + editing)",
            "api_host": self._base_url,
            "trigger_word_configured": bool(self.trigger_word),
        }

    def _reference_content(self, reference: str) -> dict | None:
        """把远程地址或本地图片转换成万相消息中的 image 内容。"""

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

    def _compose_prompt(self, request: ImageGenerationRequest, variant: CandidateVariant) -> str:
        """注入 LoRA 触发词，并把万相不支持的负面词转为正向排除指令。"""

        prompt = f"{request.positive_prompt}, {variant.prompt_suffix}".strip(", ")
        if request.negative_prompt:
            prompt = f"{prompt}\n画面中不得出现：{request.negative_prompt[:500]}"
        if self.trigger_word and self.trigger_word.casefold() not in prompt.casefold():
            prompt = f"{self.trigger_word}, {prompt}"
        # 万相 2.7 的文本提示词上限为 5000 字符，触发词放在开头可避免被截断。
        return prompt[:5000]

    @staticmethod
    def _provider_message(payload: object, fallback: str) -> str:
        """从阿里云错误响应中提取可读信息。"""

        if not isinstance(payload, dict):
            return fallback
        code = payload.get("code") or (payload.get("output") or {}).get("code")
        message = payload.get("message") or (payload.get("output") or {}).get("message")
        return ": ".join(str(item) for item in (code, message) if item) or fallback

    async def _submit_task(self, payload: dict) -> tuple[str, str]:
        """创建异步生成任务，返回 task_id 和 request_id。"""

        try:
            response = await self._client.post(
                self._create_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "X-DashScope-Async": "enable",
                },
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                detail = self._provider_message(exc.response.json(), "请求被拒绝")
            except ValueError:
                detail = "请求被拒绝"
            request_id = exc.response.headers.get("x-request-id", "")
            suffix = f"，request_id={request_id}" if request_id else ""
            raise ProviderError(f"万相 LoRA 任务创建失败（HTTP {exc.response.status_code}）：{detail}{suffix}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"无法连接万相 LoRA 服务：{type(exc).__name__}") from exc

        body = response.json()
        output = body.get("output") if isinstance(body, dict) else None
        task_id = output.get("task_id") if isinstance(output, dict) else None
        if not task_id:
            raise ProviderError(f"万相 LoRA 响应缺少 task_id：{self._provider_message(body, 'unknown response')}")
        request_id = response.headers.get("x-request-id") or body.get("request_id") or ""
        return str(task_id), str(request_id)

    async def _wait_for_task(self, task_id: str) -> tuple[dict, str]:
        """轮询任务，成功时返回完整响应；失败或超时时抛出供应商错误。"""

        deadline = time.monotonic() + self.timeout_seconds
        task_url = f"{self._base_url}/api/v1/tasks/{task_id}"
        while time.monotonic() < deadline:
            await asyncio.sleep(self.poll_interval_seconds)
            try:
                response = await self._client.get(
                    task_url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                try:
                    detail = self._provider_message(exc.response.json(), "查询被拒绝")
                except ValueError:
                    detail = "查询被拒绝"
                raise ProviderError(f"万相 LoRA 任务查询失败（HTTP {exc.response.status_code}）：{detail}") from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"无法查询万相 LoRA 任务：{type(exc).__name__}") from exc

            body = response.json()
            output = body.get("output") if isinstance(body, dict) else None
            status = str((output or {}).get("task_status", "UNKNOWN")).upper()
            if status == "SUCCEEDED":
                return body, str(response.headers.get("x-request-id") or body.get("request_id") or "")
            if status in TERMINAL_FAILURE_STATES:
                detail = self._provider_message(body, f"task_status={status}")
                raise ProviderError(f"万相 LoRA 生成失败：{detail}，task_id={task_id}")

        raise ProviderError(f"万相 LoRA 生成超时（{self.timeout_seconds:.0f} 秒），task_id={task_id}")

    async def _generate_variant(
        self,
        request: ImageGenerationRequest,
        variant: CandidateVariant,
        index: int,
    ) -> GeneratedImage:
        prompt = self._compose_prompt(request, variant)
        variant_seed = (request.seed + variant.seed_offset + index) % 2147483648
        content: list[dict] = []
        # ArtFlow 最多接收 5 张参考图；万相 2.7 的官方上限为 9 张。
        for reference in request.reference_images[:5]:
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
                "seed": variant_seed,
                "watermark": self.watermark,
            },
        }

        async with self._semaphore:
            task_id, submit_request_id = await self._submit_task(payload)
            result_payload, result_request_id = await self._wait_for_task(task_id)

        urls = _find_image_urls(result_payload)
        if not urls:
            raise ProviderError(f"万相 LoRA 成功响应中没有图片地址，task_id={task_id}")
        source_url = urls[0]
        try:
            download = await self._client.get(source_url)
            download.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"万相结果图片下载失败，task_id={task_id}") from exc

        suffix = Path(urlparse(source_url).path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".png"
        image_id = f"img_{uuid.uuid4().hex[:12]}"
        filename = f"{request.run_id}-{variant.label.lower()}-{image_id}{suffix}"
        destination = self.images_dir / filename
        self.images_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(destination.write_bytes, download.content)

        return GeneratedImage(
            id=image_id,
            label=variant.label,
            title=variant.title,
            variation=variant.variation,
            file_path=str(destination),
            public_url=f"/storage/images/{filename}",
            prompt=prompt,
            seed=variant_seed,
            width=request.width,
            height=request.height,
            backend=self.name,
            model=self.model,
            negative_prompt=request.negative_prompt,
            variant_key=variant.key,
            prompt_id=task_id,
            workflow_template="wan_lora_async_v1",
            request_json={
                "model": self.model,
                "generation_mode": request.generation_mode,
                "size": f"{request.width}*{request.height}",
                "reference_count": len(content) - 1,
                "variant": variant.model_dump(),
                "task_id": task_id,
                "submit_request_id": submit_request_id,
                "result_request_id": result_request_id,
            },
            generation_params={
                "seed": variant_seed,
                "watermark": self.watermark,
                "trigger_word_configured": bool(self.trigger_word),
            },
            parent_image_id=request.parent_image_id,
            source_turn_id=request.source_turn_id,
            version_number=request.version_number,
        )

    async def generate(self, request: ImageGenerationRequest) -> list[GeneratedImage]:
        """按候选提示词并发创建任务，并保持配置的并发上限。"""

        return await asyncio.gather(
            *(self._generate_variant(request, variant, index) for index, variant in enumerate(request.variants))
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
