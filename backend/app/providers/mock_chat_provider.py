"""Deterministic text provider for offline development and automated tests."""

from __future__ import annotations

import asyncio
import json

from app.providers.base import ChatResult


class MockChatProvider:
    name = "mock"

    def __init__(self, model: str = "artflow-mock-agent") -> None:
        self.model = model

    async def health(self) -> dict:
        return {"available": True, "mode": "deterministic offline agents", "model": self.model}

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback: dict,
    ) -> tuple[dict, ChatResult]:
        await asyncio.sleep(0.025)
        content = json.dumps(fallback, ensure_ascii=False)
        return fallback, ChatResult(
            content=content,
            model=self.model,
            input_tokens=max(1, (len(system_prompt) + len(user_prompt)) // 4),
            output_tokens=max(1, len(content) // 4),
            latency_ms=25,
        )

