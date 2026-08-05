from pydantic import BaseModel, Field


class Constraint(BaseModel):
    id: str
    description: str
    verifiable: bool = True
    expected_value: str | int | float | bool | None = None


class OutputSpec(BaseModel):
    count: int = Field(ge=1, le=4)
    aspect_ratio: str


class Brief(BaseModel):
    subject: str
    asset_type: str
    hard_constraints: list[Constraint]
    soft_constraints: list[str]
    locked_elements: list[str]
    negative_constraints: list[str]
    output: OutputSpec
