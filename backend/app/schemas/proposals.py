from typing import Literal

from pydantic import BaseModel, Field


AgentName = Literal["composition", "character", "color"]


class AgentProposal(BaseModel):
    proposal_id: str
    agent: AgentName
    attempt: int = Field(ge=1, le=3)
    summary: str
    decisions: dict
    constraints_addressed: list[str]
    prompt_fragment: str
    revision_applied: list[str] = Field(default_factory=list)


class CuratorSelection(BaseModel):
    selected_parts: dict[str, dict]
    rationale: str
    discarded: list[dict] = Field(default_factory=list)
    unresolved_risks: list[str] = Field(default_factory=list)
    final_prompt_plan: dict
