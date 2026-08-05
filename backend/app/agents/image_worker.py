from dataclasses import asdict

from app.agents.common import emit_started, make_event
from app.image_backends.base import ImageBackend
from app.schemas.image_request import ImageGenerationRequest
from app.services.agent_log_service import AgentLogService


def make_image_worker(backend: ImageBackend, logs: AgentLogService):
    async def image_worker(state: dict) -> dict:
        emit_started(
            agent="image_worker",
            stage="generation",
            title="Image Worker",
            summary=f"正在调用 {backend.name.upper()} 生成受控候选图…",
        )
        request = ImageGenerationRequest.model_validate(state.get("workflow_request", {}))
        images = await backend.generate(request)
        candidates = [asdict(image) for image in images]
        invocation = logs.record(
            state=state,
            agent="image_worker",
            status="completed",
            model=request.base_model,
            input_text=request.positive_prompt,
            output_text=f"生成 {len(candidates)} 张本地归档图片",
            structured_output={
                "image_ids": [image["id"] for image in candidates],
                "generation_mode": request.generation_mode,
            },
            reason="执行 Prompt Compiler 生成的模型请求",
        )
        event = make_event(
            event_type="image_completed",
            agent="image_worker",
            stage="generation",
            status="completed",
            title="Image Worker",
            summary=f"{len(candidates)} 张候选图已生成，工作流与模型参数已归档。",
            payload={
                "backend": backend.name,
                "image_ids": [image["id"] for image in candidates],
                "workflow_paths": [image["workflow_path"] for image in candidates],
                "invocation_id": invocation["id"],
            },
        )
        return {
            "candidate_images": candidates,
            "events": [event],
            "status": "completed",
        }

    return image_worker
