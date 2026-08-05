"""Assistant Agent.

Responsibilities: write the user-facing reply after discussion or generation.
Input: route, Agent decisions, selected concept, generated image count.
Output: concise Chinese assistant message.
Exclusions: cannot silently change professional Agent outputs or image parameters.
"""

from __future__ import annotations

from app.agents.common import AgentRuntime, emit_started, make_event


def make_assistant_agent(runtime: AgentRuntime):
    async def assistant_agent(state: dict) -> dict:
        emit_started(
            agent="assistant_agent",
            stage="response",
            title="Assistant Agent",
            summary="正在整理本轮结果与下一步可修改方向…",
        )
        count = len(state.get("candidate_images", []))
        route = state.get("routing", {}).get("route", "generate")
        fallback_message = (
            f"已基于当前选中版本生成 {count} 张新候选。你可以先选择一张，再继续告诉我局部修改方向。"
            if count
            else "我已结合当前项目记忆整理了答复；如果要继续出图，请直接描述希望修改的视觉部分。"
        )
        output, invocation = await runtime.call_json(
            state=state,
            agent="assistant_agent",
            role="用户沟通 Agent",
            task=(
                f"本轮 route={route}、生成图片数={count}。输出 JSON："
                '{"message":"简洁中文答复"}。说明完成了什么，并给出一个自然的下一步。'
            ),
            fallback={"message": fallback_message},
            reason="生成最终用户可见回复",
        )
        message = str(output.get("message") or fallback_message)[:1000]
        event = make_event(
            event_type="agent_completed",
            agent="assistant_agent",
            stage="response",
            status="completed",
            title="Assistant Agent",
            summary="已生成本轮对话回复。",
            payload={"message": message, "invocation_id": invocation["id"]},
        )
        return {"assistant_message": message, "events": [event], "status": "completed"}

    return assistant_agent
