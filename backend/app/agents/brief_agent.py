"""Brief Agent.

Responsibilities: turn the current request into testable constraints and output specs.
Input: current turn, project memory, references, aspect ratio, candidate count.
Output: hard/soft constraints, locked elements, negative constraints, output spec.
Exclusions: does not choose composition, character styling, palette, or final prompt.
"""

from __future__ import annotations

import re

from app.agents.common import AgentRuntime, emit_started, make_event


NUMBER_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}


def extract_arm_count(request: str) -> int | None:
    match = re.search(r"([一二三四五六七八\d]+)条[^，。；]*?(?:手臂|机械臂)", request)
    if not match:
        return None
    raw = match.group(1)
    return int(raw) if raw.isdigit() else NUMBER_MAP.get(raw)


def _fallback_brief(state: dict) -> dict:
    request = state["user_request"]
    hard = [{"id": "hc_request", "description": request, "verifiable": True, "expected_value": True}]
    locked = list(state.get("locked_constraints", []))
    arm_count = extract_arm_count(request)
    if arm_count is not None:
        hard.append({"id": "hc_arm_count", "description": f"角色必须有 {arm_count} 条机械手臂", "verifiable": True, "expected_value": arm_count})
        if f"{arm_count} 条机械手臂" not in locked:
            locked.append(f"{arm_count} 条机械手臂")
    return {
        "subject": request[:120],
        "asset_type": "game_art_concept",
        "hard_constraints": hard,
        "soft_constraints": ["保持游戏美术可读性", "延续已选中版本的有效设计"],
        "locked_elements": locked,
        "negative_constraints": list((state.get("memory") or {}).get("rejected_directions") or []),
        "output": {"count": int(state.get("image_count", 4)), "aspect_ratio": state.get("aspect_ratio", "1:1")},
    }


def make_brief_agent(runtime: AgentRuntime):
    async def brief_agent(state: dict) -> dict:
        emit_started(agent="brief_agent", stage="brief", title="Brief Agent", summary="正在提取本轮可验证约束与输出规格…")
        fallback = _fallback_brief(state)
        output, invocation = await runtime.call_json(
            state=state,
            agent="brief_agent",
            role="需求简报 Agent",
            task=(
                "输出 subject、asset_type、hard_constraints、soft_constraints、locked_elements、"
                "negative_constraints、output。硬约束必须可验证；不得丢失 memory 中已锁定且未解除的条件。"
            ),
            fallback=fallback,
            reason="把自然语言转换为可审核简报",
        )
        brief = {**fallback, **{key: value for key, value in output.items() if value is not None}}
        locked = list(dict.fromkeys([*state.get("locked_constraints", []), *brief.get("locked_elements", [])]))
        brief["locked_elements"] = locked
        event = make_event(
            event_type="agent_completed",
            agent="brief_agent",
            stage="brief",
            status="completed",
            title="Brief Agent",
            summary=f"提取 {len(brief.get('hard_constraints', []))} 个硬约束，并保留 {len(locked)} 个锁定条件。",
            payload={"constraints": brief, "invocation_id": invocation["id"]},
        )
        return {"constraints": brief, "locked_constraints": locked, "events": [event], "status": "briefing"}

    return brief_agent
