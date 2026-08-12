"""Image Agent：把已审核方案编译为请求并调用图像后端。"""

from __future__ import annotations

from app.agents.common import AgentRuntime
from app.agents.image_worker import make_image_worker
from app.agents.workflow_compiler import make_prompt_compiler
from app.image_backends.base import ImageBackend
from app.services.agent_log_service import AgentLogService


def make_image_agent(
    runtime: AgentRuntime,
    backend: ImageBackend,
    logs: AgentLogService,
):
    """将原Prompt Compiler和Image Worker合并为一个活跃Agent节点。"""

    compiler = make_prompt_compiler(
        runtime,
        agent_name="image_agent",
        agent_title="Image Agent",
    )
    worker = make_image_worker(
        backend,
        logs,
        agent_name="image_agent",
        agent_title="Image Agent",
    )

    async def image_agent(state: dict) -> dict:
        compiled = await compiler(state)
        generated = await worker({**state, **compiled})
        return {
            "workflow_request": compiled["workflow_request"],
            "image_count": compiled["image_count"],
            "candidate_images": generated["candidate_images"],
            "events": [*compiled.get("events", []), *generated.get("events", [])],
            "status": generated.get("status", "completed"),
        }

    return image_agent
