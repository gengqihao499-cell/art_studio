from pydantic import BaseModel, Field

from app.schemas.proposals import AgentName


class AgentReview(BaseModel):
    review_id: str
    proposal_id: str
    agent: AgentName
    approved: bool
    attempt: int = Field(ge=1, le=3)
    score: int = Field(ge=0, le=100)
    summary: str
    failed_constraints: list[str] = Field(default_factory=list)
    revision_instructions: list[str] = Field(default_factory=list)
