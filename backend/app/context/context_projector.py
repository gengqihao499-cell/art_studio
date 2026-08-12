"""上下文引擎第 4 层：按 Agent 职责投影读取时上下文。

各 Agent 共享同一份规范状态，但只接收完成自身任务所需的记忆字段；风格配置、
本轮风格圣经和参考图会显式进入投影，防止 Context Collapse 时丢失风格约束。
"""

from __future__ import annotations


AGENT_MEMORY_FIELDS: dict[str, tuple[str, ...]] = {
    # 子 Agent 正常运行时使用更严格的任务信封隔离；这里保留同职责的
    # 最小字段白名单，供诊断、测试和可能的只读投影调用使用。
    "composition_agent": (
        "project_goal",
        "locked_constraints",
        "composition_facts",
        "active_image",
    ),
    "subject_agent": (
        "project_goal",
        "locked_constraints",
        "character_facts",
        "active_image",
    ),
    "style_agent": (
        "project_goal",
        "locked_constraints",
        "style_decisions",
        "active_image",
    ),
    "supervisor_agent": (
        "project_goal",
        "locked_constraints",
        "style_decisions",
        "character_facts",
        "composition_facts",
        "rejected_directions",
        "active_image",
        "open_questions",
    ),
    "image_worker": ("project_goal", "locked_constraints", "style_decisions", "active_image"),
    "prompt_compiler": (
        "project_goal",
        "locked_constraints",
        "style_decisions",
        "character_facts",
        "composition_facts",
        "active_image",
    ),
    # 5-Agent架构中的Image Agent合并了Prompt Compiler和Image Worker，
    # 只需要编译图像请求所需的项目事实，不读取完整长期记忆。
    "image_agent": (
        "project_goal",
        "locked_constraints",
        "style_decisions",
        "character_facts",
        "composition_facts",
        "active_image",
    ),
}


class ContextProjector:
    """把完整运行状态裁剪成指定 Agent 的最小可用上下文。"""

    def project(self, state: dict, agent: str) -> dict:
        """返回只读投影；不会修改原始 state 或长期记忆。"""

        packet = dict(state.get("context_packet") or {})
        memory = dict(state.get("memory") or packet.get("memory") or {})
        style_profile = dict(state.get("style_profile") or {})
        style_bible = dict(style_profile.get("style_bible") or {})
        # 文本 Agent 只需要 visual。隐藏 ComfyUI 的 generation/LoRA 配置，避免无效触发词
        # 被 Qwen 文本 Agent 误编入 Qwen Image 的提示词。
        projected_style_profile = {
            "id": style_profile.get("id"),
            "name": style_profile.get("name"),
            "style_bible": {"visual": style_bible.get("visual", {})},
        }
        fields = AGENT_MEMORY_FIELDS.get(agent)
        if fields:
            memory = {key: memory.get(key) for key in fields if key in memory}
        return {
            "claude_md": packet.get("claude_md", ""),
            "current_request": state.get("user_request", ""),
            "world_context": state.get("world_context", ""),
            "memory": memory,
            "recent_messages": packet.get(
                "messages",
                state.get("recent_messages", []),
            ),
            "retrieved_memories": packet.get("retrieved_memories", []),
            "locked_constraints": state.get("locked_constraints", []),
            "selected_image": state.get("parent_image", {}),
            "style_profile": projected_style_profile,
            "style_bible": state.get("style_bible", {}),
            "reference_images": state.get("reference_images", []),
            "context_layers": packet.get("layers", {}),
        }
