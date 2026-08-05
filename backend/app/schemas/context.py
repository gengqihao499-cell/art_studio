"""API payloads for the project memory file."""

from pydantic import BaseModel, Field


class ClaudeMemoryUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)
