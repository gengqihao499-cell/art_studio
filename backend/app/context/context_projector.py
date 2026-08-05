"""Layer 4: build a role-specific, read-time view of canonical context."""

from __future__ import annotations


AGENT_MEMORY_FIELDS: dict[str, tuple[str, ...]] = {
    "composition_agent": ("project_goal", "locked_constraints", "composition_facts", "active_image"),
    "character_agent": ("project_goal", "locked_constraints", "character_facts", "active_image"),
    "color_agent": ("project_goal", "locked_constraints", "style_decisions", "active_image"),
    "image_worker": ("project_goal", "locked_constraints", "style_decisions", "active_image"),
    "prompt_compiler": (
        "project_goal",
        "locked_constraints",
        "style_decisions",
        "character_facts",
        "composition_facts",
        "active_image",
    ),
}


class ContextProjector:
    def project(self, state: dict, agent: str) -> dict:
        packet = dict(state.get("context_packet") or {})
        memory = dict(state.get("memory") or packet.get("memory") or {})
        fields = AGENT_MEMORY_FIELDS.get(agent)
        if fields:
            memory = {key: memory.get(key) for key in fields if key in memory}
        return {
            "claude_md": packet.get("claude_md", ""),
            "current_request": state.get("user_request", ""),
            "world_context": state.get("world_context", ""),
            "memory": memory,
            "recent_messages": packet.get("messages", state.get("recent_messages", [])),
            "retrieved_memories": packet.get("retrieved_memories", []),
            "locked_constraints": state.get("locked_constraints", []),
            "selected_image": state.get("parent_image", {}),
            "context_layers": packet.get("layers", {}),
        }
