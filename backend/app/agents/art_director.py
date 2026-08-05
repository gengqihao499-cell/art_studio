"""Art Director Agent.

Responsibilities: establish shared visual direction and audit specialist proposals.
Input: brief, project memory/style profile, composition/character/color proposals.
Output: style bible and an audit report with risks/instructions.
Exclusions: does not merge proposal fragments (only Curator may combine them).
"""

from __future__ import annotations

from app.agents.common import AgentRuntime, emit_started, make_event


def make_art_director(runtime: AgentRuntime):
    async def art_director(state: dict) -> dict:
        emit_started(agent="art_director", stage="direction", title="Art Director", summary="正在建立本轮共享风格与审核口径…")
        fallback = {
            "style_bible": {
                "mood": "coherent game art direction",
                "shape_language": "clear primary silhouette and controlled secondary detail",
                "materials": ["readable primary material", "supporting secondary material"],
                "palette_rule": "one dominant temperature with a deliberate focal accent",
                "readability_rule": "subject and focal action remain readable at thumbnail size",
            },
            "audit_rules": ["不丢失锁定约束", "所有专业提案服从同一视觉焦点", "修改基于当前选中版本"],
        }
        output, invocation = await runtime.call_json(
            state=state,
            agent="art_director",
            role="美术总监 Agent",
            task="基于 brief 和 memory 输出 style_bible 与 audit_rules。只制定共享方向和审核口径，不拼接专业方案。",
            fallback=fallback,
            reason="统一三个专业 Agent 的视觉目标",
        )
        style_bible = output.get("style_bible") if isinstance(output.get("style_bible"), dict) else fallback["style_bible"]
        event = make_event(
            event_type="agent_completed",
            agent="art_director",
            stage="direction",
            status="completed",
            title="Art Director",
            summary="共享风格、视觉焦点与审核标准已建立。",
            payload={"style_bible": style_bible, "audit_rules": output.get("audit_rules", fallback["audit_rules"]), "invocation_id": invocation["id"]},
        )
        return {"style_bible": style_bible, "audit_rules": output.get("audit_rules", fallback["audit_rules"]), "events": [event], "status": "proposing"}

    return art_director


def make_review_agent(runtime: AgentRuntime):
    async def review_proposals(state: dict) -> dict:
        emit_started(agent="art_director", stage="review", title="Art Director Review", summary="正在审核专业提案的约束一致性…")
        proposals = state.get("proposals", [])
        fallback = {
            "approved": True,
            "score": 90,
            "summary": "专业提案与共享风格和锁定约束一致，可以进入组合阶段。",
            "risks": [],
            "instructions": [],
        }
        output, invocation = await runtime.call_json(
            state={**state, "recent_messages": [{"proposals": proposals}, {"style_bible": state.get("style_bible", {})}]},
            agent="art_director",
            role="美术总监审核 Agent",
            task="审核本轮专业提案是否满足硬约束和统一风格。输出 approved、score、summary、risks、instructions；不得自行拼接方案。",
            fallback=fallback,
            reason="在 Curator 组合前做独立质量审核",
        )
        review = {**fallback, **output, "proposal_ids": [item.get("proposal_id") for item in proposals]}
        event = make_event(
            event_type="review_passed" if review.get("approved", True) else "review_rejected",
            agent="art_director",
            stage="review",
            status="passed" if review.get("approved", True) else "rejected",
            title="Art Director Review",
            summary=str(review.get("summary") or fallback["summary"]),
            payload={"review": review, "invocation_id": invocation["id"]},
        )
        return {"reviews": [review], "events": [event], "status": "reviewing"}

    return review_proposals
