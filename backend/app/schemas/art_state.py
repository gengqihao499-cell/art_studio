import operator
from typing import Annotated, Literal, TypedDict

from app.graph.reducers import merge_attempts


class ArtDesignState(TypedDict, total=False):
    thread_id: str
    run_id: str
    project_id: str
    project_name: str
    session_id: str
    turn_id: str
    turn_sequence: int
    version_number: int
    user_request: str
    reference_images: list[str]
    world_context: str
    aspect_ratio: str
    image_count: int
    image_backend: str
    image_model: str
    parent_image: dict
    recent_messages: list[dict]
    context_packet: dict
    memory: dict
    locked_constraints: list[str]
    compress_context: bool
    context_was_compressed: bool
    routing: dict
    audit_rules: list[str]
    style_profile: dict
    constraints: dict
    style_bible: dict
    proposals: Annotated[list[dict], operator.add]
    reviews: Annotated[list[dict], operator.add]
    events: Annotated[list[dict], operator.add]
    attempts: Annotated[dict[str, int], merge_attempts]
    selected_concept: dict | None
    workflow_request: dict | None
    candidate_images: list[dict]
    assistant_message: str
    status: Literal[
        "briefing",
        "proposing",
        "reviewing",
        "curating",
        "generating",
        "completed",
        "failed",
    ]
