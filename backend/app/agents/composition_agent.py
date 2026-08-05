"""Composition Agent.

Responsibilities: camera, framing, scale, spatial hierarchy, subject placement.
Input: brief, shared style bible, selected image metadata, current instruction.
Output: one traceable composition proposal and prompt fragment.
Exclusions: does not redesign character identity or decide the final palette.
"""

from __future__ import annotations

import uuid

from app.agents.common import AgentRuntime, emit_started, make_event


def make_composition_agent(runtime: AgentRuntime):
    async def composition_agent(state: dict) -> dict:
        selected = set(state.get("routing", {}).get("specialists", []))
        if "composition" not in selected:
            invocation = runtime.skip(state=state, agent="composition_agent", reason="当前指令不涉及构图、镜头或空间层次")
            event = make_event(event_type="agent_skipped", agent="composition_agent", stage="proposal", status="completed", title="Composition Agent", summary="本轮跳过：当前修改不涉及构图。", payload={"invocation_id": invocation["id"]})
            return {"events": [event]}
        emit_started(agent="composition_agent", stage="proposal", title="Composition Agent", summary="正在处理镜头、主体占比与空间层次…")
        fallback = {
            "summary": "延续当前版本的主体关系，按本轮要求调整镜头和视觉层次。",
            "decisions": {"camera": "purposeful game-concept framing", "subject_coverage": 0.65, "full_subject": True, "depth_layers": 3},
            "constraints_addressed": ["hc_request"],
            "prompt_fragment": "purposeful composition, readable subject placement, clear foreground midground background",
        }
        output, invocation = await runtime.call_json(
            state=state, agent="composition_agent", role="构图 Agent",
            task="只提出镜头、构图、主体占比和空间层次方案。输出 summary、decisions、constraints_addressed、prompt_fragment。",
            fallback=fallback, reason=state.get("routing", {}).get("reason", "构图维度被选中"),
        )
        proposal = {**fallback, **output, "proposal_id": f"composition_{uuid.uuid4().hex[:10]}", "agent": "composition", "attempt": 1}
        event = make_event(event_type="agent_completed", agent="composition_agent", stage="proposal", status="completed", title="Composition Agent", summary=str(proposal["summary"]), payload={"proposal": proposal, "invocation_id": invocation["id"]})
        return {"proposals": [proposal], "attempts": {"composition": 1}, "events": [event]}

    return composition_agent
