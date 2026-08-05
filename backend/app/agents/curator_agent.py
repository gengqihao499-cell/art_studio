"""Curator Agent — the only proposal-combination boundary.

Responsibilities: select and combine audited specialist fragments into one concept.
Input: brief, Art Director audit, composition/character/color proposals, memory.
Output: traceable selected parts, discarded parts, risks, final prompt plan.
Exclusions: does not invent new specialist decisions or call an image model.
"""

from __future__ import annotations

from app.agents.common import AgentRuntime, emit_started, make_event


def make_curator_agent(runtime: AgentRuntime):
    async def curator_agent(state: dict) -> dict:
        emit_started(agent="curator_agent", stage="curation", title="Curator Agent", summary="正在组合已审核的专业 Agent 输出…")
        proposals = state.get("proposals", [])
        fallback_parts = {
            item["agent"]: {
                "proposal_id": item.get("proposal_id"),
                "reason": "本轮该专业维度被选中并通过总监审核",
                "prompt_fragment": item.get("prompt_fragment", ""),
            }
            for item in proposals
        }
        fallback = {
            "selected_parts": fallback_parts,
            "rationale": "组合本轮已执行的专业 Agent 输出，并继承未修改维度的当前版本与项目记忆。",
            "discarded": [],
            "unresolved_risks": list((state.get("reviews") or [{}])[-1].get("risks", [])) if state.get("reviews") else [],
            "final_prompt_plan": {
                "base_request": state.get("user_request", ""),
                "preserve": state.get("locked_constraints", []),
                "specialist_fragments": [item.get("prompt_fragment", "") for item in proposals],
                "style_bible": state.get("style_bible", {}),
            },
        }
        output, invocation = await runtime.call_json(
            state={**state, "recent_messages": [{"proposals": proposals}, {"review": state.get("reviews", [])}]},
            agent="curator_agent",
            role="方案策展与组合 Agent",
            task=(
                "这是唯一允许组合专业提案的步骤。只使用已有 proposals 与审核结果，输出 selected_parts、"
                "rationale、discarded、unresolved_risks、final_prompt_plan；未执行维度继承当前版本，不得凭空重写。"
            ),
            fallback=fallback,
            reason="把独立专业提案合并为单一可追踪概念",
        )
        selection = {**fallback, **output}
        event = make_event(
            event_type="curator_selected",
            agent="curator_agent",
            stage="curation",
            status="completed",
            title="Curator Agent",
            summary=f"已组合 {len(selection.get('selected_parts', {}))} 个本轮专业输出；其他维度继承当前版本。",
            payload={"selection": selection, "invocation_id": invocation["id"], "combination_boundary": True},
        )
        return {"selected_concept": selection, "events": [event], "status": "curating"}

    return curator_agent
