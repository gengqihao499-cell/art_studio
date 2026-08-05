"""Character Agent.

Responsibilities: anatomy, silhouette, costume, props, pose, identity continuity.
Input: brief, shared style bible, selected image metadata, current instruction.
Output: one traceable character proposal and prompt fragment.
Exclusions: does not choose camera layout or global palette.
"""

from __future__ import annotations

import uuid

from app.agents.common import AgentRuntime, emit_started, make_event


def make_character_agent(runtime: AgentRuntime):
    async def character_agent(state: dict) -> dict:
        selected = set(state.get("routing", {}).get("specialists", []))
        if "character" not in selected:
            invocation = runtime.skip(state=state, agent="character_agent", reason="当前指令不涉及角色、服装、姿态或道具")
            event = make_event(event_type="agent_skipped", agent="character_agent", stage="proposal", status="completed", title="Character Agent", summary="本轮跳过：当前修改不涉及角色设计。", payload={"invocation_id": invocation["id"]})
            return {"events": [event]}
        emit_started(agent="character_agent", stage="proposal", title="Character Agent", summary="正在处理角色结构、服装、道具与剪影…")
        fallback = {
            "summary": "保留当前角色身份与锁定特征，只修改本轮明确要求的角色部分。",
            "decisions": {"identity_continuity": True, "silhouette": "readable game silhouette", "locked_features_preserved": True},
            "constraints_addressed": ["hc_request"],
            "prompt_fragment": "consistent character identity, readable anatomy and silhouette, preserve locked character features",
        }
        output, invocation = await runtime.call_json(
            state=state, agent="character_agent", role="角色设计 Agent",
            task="只提出角色结构、服装、姿态、道具和身份连续性方案。输出 summary、decisions、constraints_addressed、prompt_fragment。",
            fallback=fallback, reason=state.get("routing", {}).get("reason", "角色维度被选中"),
        )
        proposal = {**fallback, **output, "proposal_id": f"character_{uuid.uuid4().hex[:10]}", "agent": "character", "attempt": 1}
        event = make_event(event_type="agent_completed", agent="character_agent", stage="proposal", status="completed", title="Character Agent", summary=str(proposal["summary"]), payload={"proposal": proposal, "invocation_id": invocation["id"]})
        return {"proposals": [proposal], "attempts": {"character": 1}, "events": [event]}

    return character_agent
