"""提示词编译 Agent。

职责：把 Curator 选中的方案编译为模型可执行提示词，并构造受控候选变化。
输入：组合方案、硬约束、Style Profile、参考图、画幅和版本信息。
输出：与供应商无关的 ImageGenerationRequest。
边界：不选择专业提案，也不负责请求或下载图片。
"""

from __future__ import annotations

import hashlib
import re

from app.agents.common import AgentRuntime, emit_started, make_event
from app.agents.edit_intent import (
    extract_removal_target,
    is_character_target,
    is_remove_request,
    removal_negative_terms,
)
from app.schemas.image_request import CandidateVariant, ImageGenerationRequest


BASE_VARIANTS = (
    CandidateVariant(key="constraint", label="A", title="约束核心", variation="约束忠实", prompt_suffix="严格执行当前指令，只保留未被本轮修改的锁定元素", seed_offset=0, cfg_delta=0.2),
    CandidateVariant(key="composition", label="B", title="表达探索", variation="受控变化", prompt_suffix="在不改变锁定内容的前提下，提供更清晰有力的视觉表达", seed_offset=137, cfg_delta=0),
    CandidateVariant(key="silhouette", label="C", title="剪影强化", variation="清晰剪影", prompt_suffix="强化游戏美术剪影、结构分离与远距离可读性", seed_offset=281, cfg_delta=0.1),
    CandidateVariant(key="palette", label="D", title="氛围强化", variation="色彩氛围", prompt_suffix="强化材质、光影与焦点氛围，同时保持设计连续性", seed_offset=419, cfg_delta=-0.1),
)

REMOVE_VARIANTS = (
    CandidateVariant(
        key="constraint", label="A", title="完整移除", variation="删除忠实",
        prompt_suffix="彻底移除指定对象及其剪影、阴影、倒影和随身物，自然补全被遮挡背景",
        seed_offset=0, cfg_delta=0.2,
    ),
    CandidateVariant(
        key="composition", label="B", title="场景补全", variation="背景修复",
        prompt_suffix="保持未涉及区域不变，清除指定对象，在原位置延续周围材质、光影和场景结构",
        seed_offset=137, cfg_delta=0,
    ),
)

ASPECT_DIMENSIONS = {"1:1": (1024, 1024), "4:3": (1152, 864), "3:4": (864, 1152), "16:9": (1280, 720), "9:16": (720, 1280)}

VISUAL_LABELS = {
    "style_name": "风格名称",
    "rendering_medium": "表现媒介",
    "camera": "镜头",
    "pixel_rule": "像素规则",
    "shape_language": "造型语言",
    "palette_rule": "色板规则",
    "lighting_rule": "光影规则",
    "materials": "材质词典",
    "readability_rule": "可读性规则",
}


def _without_character_clauses(value: object) -> object:
    """删除会在无人场景中诱导模型重新生成人物的风格短语。"""

    markers = ("角色", "人物", "冒险者", "人类", "NPC", "类人生物")
    if isinstance(value, list):
        return [item for item in value if not any(marker in str(item) for marker in markers)]
    if not isinstance(value, str):
        return value
    clauses = [part.strip() for part in re.split(r"[、；;]", value) if part.strip()]
    return "、".join(
        part for part in clauses if not any(marker.lower() in part.lower() for marker in markers)
    )


def _visual_contract(state: dict, *, suppress_character: bool = False) -> tuple[str, list[str]]:
    """把结构化 Style Profile 编译成不可被 LLM 遗漏的确定性提示词。"""

    profile_visual = (
        (state.get("style_profile") or {})
        .get("style_bible", {})
        .get("visual", {})
    )
    visual = profile_visual or state.get("style_bible", {})
    if not isinstance(visual, dict):
        return "", []

    parts: list[str] = []
    for key, label in VISUAL_LABELS.items():
        value = visual.get(key)
        if suppress_character:
            value = _without_character_clauses(value)
        if isinstance(value, list):
            value = "、".join(str(item) for item in value if item)
        if value:
            parts.append(f"{label}：{value}")
    forbidden = [str(item) for item in visual.get("forbidden", []) if item]
    return "；".join(parts), forbidden


def _merge_terms(*groups: object) -> list[str]:
    """按出现顺序合并提示词条目并去重，避免重复消耗上下文。"""

    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        items = group if isinstance(group, list) else str(group or "").replace("，", ",").split(",")
        for item in items:
            term = str(item).strip()
            if term and term not in seen:
                seen.add(term)
                merged.append(term)
    return merged


def _reference_instruction(*, has_parent: bool, reference_count: int) -> str:
    """说明参考图的用途和顺序，抑制模型照抄主体、构图、UI 或 Logo。"""

    if reference_count == 0:
        return ""
    if has_parent:
        extra = (
            "；其余图片仅用于学习像素技法、色板、像素密度和材质表达，"
            "不得复制其中的角色、具体构图、UI、文字、Logo 或现有游戏素材"
            if reference_count > 1
            else ""
        )
        return (
            "参考图规则：第1张图是必须编辑的父图；在它的基础上严格执行当前编辑指令，"
            f"未被当前指令修改的区域保持连续和稳定{extra}"
        )
    return (
        "参考图规则：所有输入图片都仅为风格参考；只学习像素技法、色板、像素密度和材质表达，"
        "不得复制参考图的角色身份、具体构图、UI、文字、Logo 或现有游戏素材"
    )


def _lora_trigger_words(state: dict) -> list[str]:
    """读取 Style Profile 中仅供本地 LoRA 使用、不得发给 Qwen Image 的触发词。"""

    generation = (
        (state.get("style_profile") or {})
        .get("style_bible", {})
        .get("generation", {})
    )
    return [
        str(item.get("trigger_word"))
        for item in generation.get("loras", [])
        if isinstance(item, dict) and item.get("trigger_word")
    ]


def _clean_model_prompt(prompt: object, *, remove_terms: list[str]) -> str:
    """移除模型重复生成的编译器尾段和不适用于当前后端的 LoRA 触发词。"""

    text = str(prompt or "").strip()
    marker_positions = [
        position
        for marker in ("\n必须遵守的风格契约：", "\n参考图规则：")
        if (position := text.find(marker)) >= 0
    ]
    if marker_positions:
        text = text[:min(marker_positions)].strip()
    for term in remove_terms:
        text = text.replace(term, "")
    return re.sub(r"(?:\s*,\s*){2,}", ", ", text).strip(" ,\n")


def _without_character_prompt_clauses(prompt: str) -> str:
    """人物删除操作下，清除模型自由文本中可能残留的角色正向描述。"""

    clauses = [part.strip() for part in re.split(r"[，,；;\n]", prompt) if part.strip()]
    return "，".join(
        part for part in clauses if not is_character_target(part, part)
    )


def _removal_instruction(request: str, target: str) -> str:
    """生成对象删除的最高优先级正向指令，要求同步完成背景修复。"""

    return (
        f"当前编辑指令（最高优先级）：{request}\n"
        f"对象移除任务：完全移除“{target}”及其身体、剪影、阴影、倒影、随身物和残留像素；"
        "根据周围地形、材质、光线和透视自然补全原先被遮挡的背景；"
        "最终画面不得出现该对象或任何替代对象。"
    )


def make_prompt_compiler(
    runtime: AgentRuntime,
    *,
    agent_name: str = "prompt_compiler",
    agent_title: str = "Prompt Compiler",
):
    """创建将 Agent 组合结果编译为图像请求的节点。"""

    async def workflow_compiler(state: dict) -> dict:
        count = 4 if int(state.get("turn_sequence", 1)) <= 1 else 2
        emit_started(agent=agent_name, stage="compile", title=agent_title, summary=f"正在编译 {count} 个受控候选提示词…")
        selection = state.get("selected_concept", {})
        user_request = state.get("user_request", "")
        remove_operation = is_remove_request(user_request)
        removal_target = extract_removal_target(user_request) if remove_operation else ""
        removes_character = bool(
            removal_target and is_character_target(removal_target, user_request)
        )
        style_contract, style_forbidden = _visual_contract(
            state,
            suppress_character=removes_character,
        )
        references = list(state.get("reference_images", []))
        parent_image = state.get("parent_image") or {}
        parent_path = parent_image.get("file_path")
        if parent_path:
            references = [parent_path, *[ref for ref in references if ref != parent_path]]
        fallback = {
            "positive_prompt": ", ".join(filter(None, [
                state.get("user_request", ""),
                str(selection.get("final_prompt_plan", "")),
                "专业游戏美术概念，设计统一，主体清晰可读",
            ])),
            "negative_prompt": ", ".join(
                _merge_terms(
                    (state.get("constraints") or {}).get("negative_constraints", []),
                    style_forbidden,
                )
            ),
        }
        output, invocation = await runtime.call_json(
            state={**state, "recent_messages": [{"selected_concept": selection}]},
            agent=agent_name,
            role="图像提示词编译 Agent",
            task=(
                "把 Curator 的 final_prompt_plan 编译为 positive_prompt 与 negative_prompt。"
                "当前 user_request 是最高优先级，不得被历史版本或父图内容覆盖。"
                "若用户要求删除对象，正向提示词必须明确完整移除并补全被遮挡背景，"
                "不得再要求保留该对象的身份或剪影。只保留父图中未被本轮修改的内容；Style Profile 是硬约束，"
                "不得自行弱化。提示词可以使用中文，关键视觉术语可保留英文括注。"
            ),
            fallback=fallback,
            reason="把组合方案转换为当前图像后端可执行请求",
        )
        width, height = ASPECT_DIMENSIONS.get(state.get("aspect_ratio", "1:1"), (1024, 1024))
        # 云端图像模型只要收到参考图片，就进入生成/编辑融合模式。
        generation_mode = "edit" if references else "create"
        reference_limit = 5 if state.get("image_backend") == "wan_lora" else 3
        reference_rule = _reference_instruction(
            has_parent=bool(parent_path),
            reference_count=len(references[:reference_limit]),
        )
        model_prompt = _clean_model_prompt(
            output.get("positive_prompt") or fallback["positive_prompt"],
            remove_terms=(
                _lora_trigger_words(state)
                if state.get("image_backend") in {"qwen_image", "wan_lora"}
                else []
            ),
        )
        if removes_character:
            model_prompt = _without_character_prompt_clauses(model_prompt)
        positive_prompt = "\n".join(
            part
            for part in (
                _removal_instruction(user_request, removal_target) if remove_operation else "",
                model_prompt,
                f"必须遵守的风格契约：{style_contract}" if style_contract else "",
                reference_rule,
            )
            if part
        )
        negative_prompt = ", ".join(
            _merge_terms(
                # 删除目标置于最前，避免供应商的 500 字负面提示词上限截断关键约束。
                removal_negative_terms(removal_target, user_request) if remove_operation else [],
                output.get("negative_prompt", ""),
                (state.get("constraints") or {}).get("negative_constraints", []),
                style_forbidden,
            )
        )
        # 千问和万相 seed 的合法范围都是 0 到 2^31-1。
        seed = int(hashlib.sha256(state["run_id"].encode()).hexdigest()[:12], 16) % 2147483648
        request = ImageGenerationRequest(
            project_id=state["project_id"], run_id=state["run_id"], backend=state.get("image_backend", "mock"),
            base_model=state.get("image_model", "configured-image-model"),
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            width=width, height=height, seed=seed,
            reference_images=references[:5], parent_image_id=parent_image.get("id"),
            source_turn_id=state.get("turn_id"), version_number=int(state.get("version_number", 1)),
            generation_mode=generation_mode,
            variants=list((REMOVE_VARIANTS if remove_operation else BASE_VARIANTS)[:count]),
            workflow_template=(
                "wan_lora_async_v1"
                if state.get("image_backend") == "wan_lora"
                else "qwen_image_v1"
            ),
        ).model_dump()
        event = make_event(
            event_type="workflow_compiled", agent=agent_name, stage="compile", status="completed",
            title=agent_title, summary=f"已编译 {count} 个受控变化；模式为 {'参考图编辑' if generation_mode == 'edit' else '首次生成'}。",
            payload={
                "backend": request["backend"],
                "model": request["base_model"],
                "generation_mode": generation_mode,
                "reference_count": len(references[:reference_limit]),
                "style_contract_applied": bool(style_contract),
                "edit_operation": "remove" if remove_operation else "modify",
                "removal_target": removal_target,
                "variant_keys": [item["key"] for item in request["variants"]],
                "invocation_id": invocation["id"],
            },
        )
        return {"workflow_request": request, "image_count": count, "events": [event], "status": "generating"}

    return workflow_compiler
