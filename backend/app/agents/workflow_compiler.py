"""Prompt Compiler Agent.

Responsibilities: translate the Curator selection into model-ready prompts and
controlled A/B/C/D variants.
Input: selected concept, constraints, aspect ratio, version/edit metadata.
Output: provider-neutral ImageGenerationRequest.
Exclusions: does not select proposals or generate/download images.
"""

from __future__ import annotations

import hashlib

from app.agents.common import AgentRuntime, emit_started, make_event
from app.schemas.image_request import CandidateVariant, ImageGenerationRequest


VARIANTS = (
    CandidateVariant(key="constraint", label="A", title="约束核心", variation="约束忠实", prompt_suffix="严格保留锁定元素与主体身份，只执行当前明确修改", seed_offset=0, cfg_delta=0.2),
    CandidateVariant(key="composition", label="B", title="表达探索", variation="受控变化", prompt_suffix="在不改变锁定内容的前提下，提供更清晰有力的视觉表达", seed_offset=137, cfg_delta=0),
    CandidateVariant(key="silhouette", label="C", title="剪影强化", variation="清晰剪影", prompt_suffix="强化游戏美术剪影、结构分离与远距离可读性", seed_offset=281, cfg_delta=0.1),
    CandidateVariant(key="palette", label="D", title="氛围强化", variation="色彩氛围", prompt_suffix="强化材质、光影与焦点氛围，同时保持设计连续性", seed_offset=419, cfg_delta=-0.1),
)

ASPECT_DIMENSIONS = {"1:1": (1024, 1024), "4:3": (1152, 864), "3:4": (864, 1152), "16:9": (1280, 720), "9:16": (720, 1280)}


def make_prompt_compiler(runtime: AgentRuntime):
    async def workflow_compiler(state: dict) -> dict:
        count = 4 if int(state.get("turn_sequence", 1)) <= 1 else 2
        emit_started(agent="prompt_compiler", stage="compile", title="Prompt Compiler", summary=f"正在编译 {count} 个受控候选提示词…")
        selection = state.get("selected_concept", {})
        fallback = {
            "positive_prompt": ", ".join(filter(None, [
                state.get("user_request", ""),
                str(selection.get("final_prompt_plan", "")),
                "professional game art concept, coherent design, high visual readability",
            ])),
            "negative_prompt": ", ".join(state.get("constraints", {}).get("negative_constraints", [])),
        }
        output, invocation = await runtime.call_json(
            state={**state, "recent_messages": [{"selected_concept": selection}]},
            agent="prompt_compiler",
            role="图像提示词编译 Agent",
            task=(
                "把 Curator 的 final_prompt_plan 编译为 positive_prompt 与 negative_prompt。"
                "必须明确保留父图身份/构图中未要求改变的内容；提示词可中英混合，但应适合千问图像模型。"
            ),
            fallback=fallback,
            reason="把组合方案转换为 Qwen Image 可执行请求",
        )
        width, height = ASPECT_DIMENSIONS.get(state.get("aspect_ratio", "1:1"), (1024, 1024))
        generation_mode = "edit" if state.get("parent_image") else "create"
        references = list(state.get("reference_images", []))
        parent_path = state.get("parent_image", {}).get("file_path")
        if parent_path:
            references = [parent_path, *[ref for ref in references if ref != parent_path]]
        request = ImageGenerationRequest(
            project_id=state["project_id"], run_id=state["run_id"], backend=state.get("image_backend", "mock"),
            base_model=state.get("image_model", "qwen-image-2.0"),
            positive_prompt=str(output.get("positive_prompt") or fallback["positive_prompt"]),
            negative_prompt=str(output.get("negative_prompt") or fallback["negative_prompt"]),
            width=width, height=height, seed=int(hashlib.sha256(state["run_id"].encode()).hexdigest()[:12], 16),
            reference_images=references[:5], parent_image_id=state.get("parent_image", {}).get("id"),
            source_turn_id=state.get("turn_id"), version_number=int(state.get("version_number", 1)),
            generation_mode=generation_mode, variants=list(VARIANTS[:count]), workflow_template="qwen_image_v1",
        ).model_dump()
        event = make_event(
            event_type="workflow_compiled", agent="prompt_compiler", stage="compile", status="completed",
            title="Prompt Compiler", summary=f"已编译 {count} 个受控变化；模式为 {'参考图编辑' if generation_mode == 'edit' else '首次生成'}。",
            payload={"backend": request["backend"], "model": request["base_model"], "generation_mode": generation_mode, "variant_keys": [item["key"] for item in request["variants"]], "invocation_id": invocation["id"]},
        )
        return {"workflow_request": request, "image_count": count, "events": [event], "status": "generating"}

    return workflow_compiler
