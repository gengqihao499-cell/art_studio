"""Shared contracts for text-model providers used by ArtFlow agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class ChatResult:
    """Normalized result returned by every chat provider."""

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    raw: dict = field(default_factory=dict)


class ChatProvider(Protocol):
    name: str
    model: str

    async def health(self) -> dict: ...

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        fallback: dict,
    ) -> tuple[dict, ChatResult]: ...


class ProviderError(RuntimeError):
    """Safe provider error. The API key and raw authorization headers are never included."""

