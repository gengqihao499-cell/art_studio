"""Qwen OpenAI-compatible chat provider for the Alibaba Cloud Beijing region."""

from __future__ import annotations

import json
import time

import httpx

from app.providers.base import ChatResult, ProviderError


def _extract_json(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.removeprefix("```json").removeprefix("```")
        clean = clean.rsplit("```", 1)[0].strip()
    try:
        value = json.loads(clean)
    except json.JSONDecodeError:
        start, end = clean.find("{"), clean.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("千问 Agent 未返回有效 JSON")
        try:
            value = json.loads(clean[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError("千问 Agent 返回的 JSON 无法解析") from exc
    if not isinstance(value, dict):
        raise ProviderError("千问 Agent 返回值必须是 JSON 对象")
    return value


class QwenChatProvider:
    name = "qwen"

    def __init__(
        self,
        *,
        api_key: str,
        workspace_id: str,
        api_host: str = "",
        model: str = "qwen-plus",
        timeout_seconds: float = 90,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key or (not workspace_id and not api_host):
            raise RuntimeError("Qwen Agent 需要 API Key 以及 Workspace ID 或 API Host")
        self.model = model
        self._api_key = api_key
        self._workspace_id = workspace_id
        base_url = api_host.strip().rstrip("/") or f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com"
        self._url = f"{base_url}/compatible-mode/v1/chat/completions"
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def health(self) -> dict:
        return {
            "available": True,
            "configured": True,
            "region": "cn-beijing",
            "model": self.model,
            "api_host": self._url.split("/compatible-mode/", 1)[0],
        }

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback: dict,
    ) -> tuple[dict, ChatResult]:
        del fallback  # Only the offline provider uses deterministic fallbacks.
        started = time.perf_counter()
        try:
            response = await self._client.post(
                self._url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            request_id = exc.response.headers.get("x-request-id", "")
            suffix = f"，request_id={request_id}" if request_id else ""
            raise ProviderError(f"千问 Agent 请求失败（HTTP {exc.response.status_code}）{suffix}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"无法连接千问 Agent 服务：{type(exc).__name__}") from exc

        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("千问 Agent 响应缺少 choices.message.content") from exc
        parsed = _extract_json(str(content))
        usage = payload.get("usage", {})
        result = ChatResult(
            content=str(content),
            model=str(payload.get("model") or self.model),
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw={"id": payload.get("id")},
        )
        return parsed, result

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
