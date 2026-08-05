"""Intent Router Agent.

Responsibilities: decide chat vs image generation and select specialist Agents.
Input: current user turn, compact memory, selected image metadata.
Output: route, specialist list, routing reason, lock/unlock changes.
Exclusions: does not create visual proposals or compile image prompts.
"""

from __future__ import annotations

from app.agents.common import AgentRuntime, emit_started, make_event


SPECIALISTS = {"composition", "character", "color"}


def _fallback_route(state: dict) -> dict:
    text = state.get("user_request", "").lower()
    chat_markers = ("为什么", "解释", "怎么", "是什么", "有哪些", "建议")
    edit_markers = ("改", "调整", "生成", "画", "设计", "增加", "减少", "换", "更")
    route = "chat" if any(key in text for key in chat_markers) and not any(key in text for key in edit_markers) else "generate"
    if int(state.get("turn_sequence", 1)) <= 1:
        selected = ["composition", "character", "color"]
    else:
        selected: list[str] = []
        if any(key in text for key in ("构图", "镜头", "位置", "大小", "月亮", "背景", "景别", "比例")):
            selected.append("composition")
        if any(key in text for key in ("角色", "服装", "表情", "脸", "手", "武器", "道具", "姿势")):
            selected.append("character")
        if any(key in text for key in ("颜色", "色彩", "冷色", "暖色", "光线", "亮度", "变暗", "材质")):
            selected.append("color")
        if route == "generate" and not selected:
            selected = ["composition", "character", "color"]
    return {
        "route": route,
        "specialists": selected,
        "reason": "根据当前指令涉及的视觉维度选择最少必要 Agent。",
        "lock_additions": [],
        "unlock_items": [],
    }


def make_intent_router(runtime: AgentRuntime):
    async def intent_router(state: dict) -> dict:
        emit_started(
            agent="intent_router",
            stage="routing",
            title="Intent Router",
            summary="正在判断本轮是讨论还是生成，并选择必要的专业 Agent…",
        )
        fallback = _fallback_route(state)
        output, invocation = await runtime.call_json(
            state=state,
            agent="intent_router",
            role="意图路由 Agent",
            task=(
                "判断用户是否要求生成/修改图像。route 只能是 generate 或 chat；"
                "specialists 只能从 composition、character、color 中选择最少必要集合；"
                "识别明确要求长期保持的 lock_additions 与明确解除的 unlock_items。"
            ),
            fallback=fallback,
            reason="确定本轮图路由和 Agent 执行范围",
        )
        route = output.get("route") if output.get("route") in {"generate", "chat"} else fallback["route"]
        specialists = [name for name in output.get("specialists", []) if name in SPECIALISTS]
        if route == "generate" and not specialists:
            specialists = fallback["specialists"] or ["composition", "character", "color"]
        routing = {
            "route": route,
            "specialists": specialists,
            "reason": str(output.get("reason") or fallback["reason"]),
            "lock_additions": list(output.get("lock_additions") or []),
            "unlock_items": list(output.get("unlock_items") or []),
        }
        locks = [item for item in state.get("locked_constraints", []) if item not in routing["unlock_items"]]
        for item in routing["lock_additions"]:
            if item and item not in locks:
                locks.append(str(item))
        event = make_event(
            event_type="agent_completed",
            agent="intent_router",
            stage="routing",
            status="completed",
            title="Intent Router",
            summary=f"本轮路由为 {route}；执行 Agent：{', '.join(specialists) if specialists else 'Assistant'}。",
            payload={"routing": routing, "invocation_id": invocation["id"]},
        )
        return {"routing": routing, "locked_constraints": locks, "events": [event]}

    return intent_router
