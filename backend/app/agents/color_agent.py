"""Color Agent.

Responsibilities: palette, lighting, value separation, material color behavior.
Input: brief, shared style bible, selected image metadata, current instruction.
Output: one traceable color/lighting proposal and prompt fragment.
Exclusions: does not reposition subjects or alter character identity.
"""

from __future__ import annotations

import uuid

from app.agents.common import AgentRuntime, emit_started, make_event


def make_color_agent(runtime: AgentRuntime):
    async def color_agent(state: dict) -> dict:
        selected = set(state.get("routing", {}).get("specialists", []))
        if "color" not in selected:
            invocation = runtime.skip(state=state, agent="color_agent", reason="当前指令不涉及色彩、光线或材质表现")
            event = make_event(event_type="agent_skipped", agent="color_agent", stage="proposal", status="completed", title="Color Agent", summary="本轮跳过：当前修改不涉及色彩与光照。", payload={"invocation_id": invocation["id"]})
            return {"events": [event]}
        emit_started(agent="color_agent", stage="proposal", title="Color Agent", summary="正在处理色板、光源、材质色与主体分离…")
        fallback = {
            "summary": "延续当前主色关系，按本轮要求调整色温、光线和焦点分离。",
            "decisions": {"value_separation": "clear", "focal_accent": "controlled", "material_response": "coherent"},
            "constraints_addressed": ["hc_request"],
            "prompt_fragment": "coherent palette, controlled focal lighting, clear value separation, believable material response",
        }
        output, invocation = await runtime.call_json(
            state=state, agent="color_agent", role="色彩与光照 Agent",
            task="只提出色板、光线、明度分离和材质色方案。输出 summary、decisions、constraints_addressed、prompt_fragment。",
            fallback=fallback, reason=state.get("routing", {}).get("reason", "色彩维度被选中"),
        )
        proposal = {**fallback, **output, "proposal_id": f"color_{uuid.uuid4().hex[:10]}", "agent": "color", "attempt": 1}
        event = make_event(event_type="agent_completed", agent="color_agent", stage="proposal", status="completed", title="Color Agent", summary=str(proposal["summary"]), payload={"proposal": proposal, "invocation_id": invocation["id"]})
        return {"proposals": [proposal], "attempts": {"color": 1}, "events": [event]}

    return color_agent
