"""Memory Agent.

Responsibilities: maintain compact structured project memory and context budget.
Input: persisted memory, recent turns, current message, locked constraints.
Output: updated memory plus a context packet used by downstream Agents.
Exclusions: never decides composition, character design, color, or image prompts.
"""

from __future__ import annotations

from app.agents.common import AgentRuntime, emit_started, make_event
from app.context import ContextEngine


MEMORY_KEYS = (
    "project_goal",
    "locked_constraints",
    "style_decisions",
    "character_facts",
    "composition_facts",
    "rejected_directions",
    "active_image",
    "open_questions",
)


def _fallback_memory(state: dict) -> dict:
    previous = dict(state.get("memory") or {})
    previous.setdefault("project_goal", state.get("user_request", "")[:240])
    previous["locked_constraints"] = list(state.get("locked_constraints", []))
    previous["active_image"] = state.get("parent_image", {})
    for key in MEMORY_KEYS:
        previous.setdefault(key, [] if key not in {"project_goal", "active_image"} else ("" if key == "project_goal" else {}))
    return {"memory": previous, "summary_note": "已更新结构化项目记忆。"}


def make_memory_agent(runtime: AgentRuntime, context_engine: ContextEngine | None = None):
    async def memory_agent(state: dict) -> dict:
        emit_started(
            agent="memory_agent",
            stage="memory",
            title="Memory Agent",
            summary="正在载入长期约束、最近对话与当前版本…",
        )
        fallback = _fallback_memory(state)
        compact_requested = bool(
            state.get("context_packet", {}).get("compaction", {}).get("requested")
        )
        try:
            output, invocation = await runtime.call_json(
                state=state,
                agent="memory_agent",
                role="上下文记忆 Agent",
                task=(
                    "把本轮信息合并进 memory。memory 必须包含 project_goal、locked_constraints、"
                    "style_decisions、character_facts、composition_facts、rejected_directions、"
                    "active_image、open_questions。保留仍有效的事实，不把猜测写成锁定约束。"
                    + (
                        "本轮正在执行 Auto-compact：必须保留关键事实并删除重复表述。"
                        if compact_requested
                        else ""
                    )
                ),
                fallback=fallback,
                attempt=int(
                    state.get("context_packet", {})
                    .get("compaction", {})
                    .get("consecutive_failures", 0)
                )
                + 1,
                reason="Auto-compact 全量摘要" if compact_requested else "更新跨轮结构化记忆",
            )
        except Exception as exc:
            # Auto-compact is an optimization, not a reason to lose the user's
            # turn. Fall back to the last good memory and open the breaker after
            # three consecutive failures. Non-compaction Memory errors keep the
            # original fail-fast behavior.
            if not compact_requested or context_engine is None:
                raise
            compaction = context_engine.memory_failed(state, exc)
            event = make_event(
                event_type=(
                    "circuit_opened"
                    if compaction["circuit_state"] == "open"
                    else "auto_compact_failed"
                ),
                agent="memory_agent",
                stage="memory",
                status="completed",
                title="Memory Agent",
                summary=(
                    "Auto-compact 已连续失败 3 次并熔断；继续使用最后有效记忆。"
                    if compaction["circuit_state"] == "open"
                    else f"Auto-compact 失败 {compaction['consecutive_failures']}/3；本轮使用最后有效记忆。"
                ),
                payload={"compaction": compaction, "fallback": True},
            )
            return {
                "memory": fallback["memory"],
                "context_was_compressed": False,
                "events": [event],
            }
        candidate = output.get("memory") if isinstance(output.get("memory"), dict) else fallback["memory"]
        memory = {key: candidate.get(key, fallback["memory"].get(key)) for key in MEMORY_KEYS}
        memory["locked_constraints"] = list(state.get("locked_constraints", memory.get("locked_constraints") or []))
        compressed = compact_requested or bool(state.get("compress_context"))
        context_packet = (
            context_engine.memory_succeeded(state, memory)
            if context_engine is not None
            else state.get("context_packet", {})
        )
        event = make_event(
            event_type="context_compressed" if compressed else "agent_completed",
            agent="memory_agent",
            stage="memory",
            status="completed",
            title="Memory Agent",
            summary=(
                f"上下文已压缩为 8 个结构化字段，保留最近 {len(state.get('recent_messages', []))} 条消息。"
                if compressed
                else "已加载结构化记忆、锁定约束与最近对话。"
            ),
            payload={"memory": memory, "compressed": compressed, "invocation_id": invocation["id"]},
        )
        return {
            "memory": memory,
            "context_packet": context_packet,
            "context_was_compressed": compressed,
            "events": [event],
        }

    return memory_agent
