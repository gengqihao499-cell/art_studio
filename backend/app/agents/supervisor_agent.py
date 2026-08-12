"""Supervisor Agent：规划、派发、汇聚和最终回复。

这是唯一可以读取父图完整状态和合并子 Agent 结果的 Agent。专业子任务在
Prepare 阶段一次性冻结；进入并行阶段后不存在向运行中子 Agent 追加消息的通道。
"""

from __future__ import annotations

import re
import uuid

from app.agents.common import AgentRuntime, emit_started, make_event
from app.context import ContextEngine
from app.schemas.agent_protocol import ChildResultEnvelope, ChildTaskEnvelope


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

SPECIALIST_TO_CHILD = {
    "composition": "composition_agent",
    "character": "subject_agent",
    "subject": "subject_agent",
    "color": "style_agent",
    "style": "style_agent",
}

CHILD_INSTRUCTIONS = {
    "composition_agent": "只处理镜头、构图、主体占比和空间层次，不修改主体身份或色板。",
    "subject_agent": "只处理角色、道具、姿态、轮廓、身份连续性和对象删除，不决定镜头或全局色板。",
    "style_agent": "只处理画风、色板、光照、材质和明暗分离，不移动主体或改写身份。",
}

CHILD_MEMORY_FIELDS = {
    "composition_agent": ("project_goal", "locked_constraints", "composition_facts", "active_image"),
    "subject_agent": ("project_goal", "locked_constraints", "character_facts", "active_image"),
    "style_agent": ("project_goal", "locked_constraints", "style_decisions", "active_image"),
}

NUMBER_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}


def extract_arm_count(request: str) -> int | None:
    """提取可验证的机械手臂数量，供 Supervisor 生成硬约束。"""

    match = re.search(r"([一二三四五六七八\d]+)条[^，。；]*?(?:手臂|机械臂)", request)
    if not match:
        return None
    raw = match.group(1)
    return int(raw) if raw.isdigit() else NUMBER_MAP.get(raw)


def _fallback_route(state: dict) -> dict:
    """模型不可用时，按关键词选择最少必要的专业子 Agent。"""

    text = state.get("user_request", "").lower()
    chat_markers = ("为什么", "解释", "怎么", "是什么", "有哪些", "建议")
    edit_markers = (
        "改", "调整", "生成", "画", "设计", "增加", "减少", "换", "更",
        "去掉", "删除", "移除", "删掉", "清除", "不要出现",
    )
    route = (
        "chat"
        if any(key in text for key in chat_markers)
        and not any(key in text for key in edit_markers)
        else "generate"
    )
    if int(state.get("turn_sequence", 1)) <= 1:
        selected = ["composition", "character", "color"]
    else:
        selected: list[str] = []
        if any(key in text for key in ("构图", "镜头", "位置", "大小", "月亮", "背景", "景别", "比例")):
            selected.append("composition")
        if any(key in text for key in ("角色", "人物", "冒险者", "npc", "服装", "表情", "脸", "手", "武器", "道具", "姿势", "去掉", "删除", "移除")):
            selected.append("character")
        if any(key in text for key in ("颜色", "色彩", "冷色", "暖色", "光线", "亮度", "变暗", "材质")):
            selected.append("color")
        if route == "generate" and not selected:
            selected = ["composition", "character", "color"]
    return {
        "route": route,
        "specialists": selected,
        "reason": "根据当前指令涉及的视觉维度选择最少必要 Agent。",
    }


def _fallback_brief(state: dict) -> dict:
    """模型不可用时，把当前请求转换为最小可审核约束。"""

    request = state["user_request"]
    hard = [
        {
            "id": "hc_request",
            "description": request,
            "verifiable": True,
            "expected_value": True,
        }
    ]
    locked = list(state.get("locked_constraints", []))
    arm_count = extract_arm_count(request)
    if arm_count is not None:
        hard.append(
            {
                "id": "hc_arm_count",
                "description": f"角色必须有 {arm_count} 条机械手臂",
                "verifiable": True,
                "expected_value": arm_count,
            }
        )
        if f"{arm_count} 条机械手臂" not in locked:
            locked.append(f"{arm_count} 条机械手臂")
    return {
        "subject": request[:120],
        "asset_type": "game_art_concept",
        "hard_constraints": hard,
        "soft_constraints": ["保持游戏美术可读性", "延续已选中版本的有效设计"],
        "locked_elements": locked,
        "negative_constraints": list(
            (state.get("memory") or {}).get("rejected_directions") or []
        ),
        "output": {
            "count": int(state.get("image_count", 4)),
            "aspect_ratio": state.get("aspect_ratio", "1:1"),
        },
    }


def _fallback_memory(state: dict) -> dict:
    previous = dict(state.get("memory") or {})
    previous.setdefault("project_goal", state.get("user_request", "")[:240])
    previous["locked_constraints"] = list(state.get("locked_constraints", []))
    previous["active_image"] = state.get("parent_image", {})
    for key in MEMORY_KEYS:
        default = "" if key == "project_goal" else ({} if key == "active_image" else [])
        previous.setdefault(key, default)
    return previous


def _fallback_direction(state: dict) -> dict:
    preset = (
        (state.get("style_profile") or {})
        .get("style_bible", {})
        .get("visual", {})
    )
    return {
        "mood": "统一且可读的游戏美术方向",
        "shape_language": "主体轮廓清晰，次要细节受控",
        "palette_rule": "主色关系统一，焦点色明确",
        "readability_rule": "缩略图尺寸下仍能识别主体与关键动作",
        **(preset if isinstance(preset, dict) else {}),
    }


def _preset_visual(state: dict) -> dict:
    value = (
        (state.get("style_profile") or {})
        .get("style_bible", {})
        .get("visual", {})
    )
    return value if isinstance(value, dict) else {}


def _normalize_specialists(values: object, fallback: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values if isinstance(values, list) else []:
        child = SPECIALIST_TO_CHILD.get(str(value))
        if child and child not in normalized:
            normalized.append(child)
    if normalized:
        return normalized
    return [SPECIALIST_TO_CHILD[item] for item in fallback if item in SPECIALIST_TO_CHILD]


def _make_child_task(state: dict, child_agent: str, instruction: str) -> ChildTaskEnvelope:
    """使用字段白名单构造子任务；不传递完整消息、检索记忆或其他提案。"""

    memory = dict(state.get("memory") or {})
    allowed_memory = {
        key: memory.get(key)
        for key in CHILD_MEMORY_FIELDS[child_agent]
        if key in memory
    }
    context = {
        "current_request": state.get("user_request", ""),
        "world_context": state.get("world_context", ""),
        "constraints": state.get("constraints", {}),
        "locked_constraints": list(state.get("locked_constraints", [])),
        "style_bible": state.get("style_bible", {}),
        "selected_image": state.get("parent_image", {}),
        "reference_images": list(state.get("reference_images", [])),
        "version_number": int(state.get("version_number", 1)),
        "memory": allowed_memory,
    }
    return ChildTaskEnvelope.create(
        task_id=f"task_{uuid.uuid4().hex[:14]}",
        parent_run_id=state["run_id"],
        project_id=state["project_id"],
        session_id=str(state.get("session_id") or ""),
        turn_id=str(state.get("turn_id") or ""),
        child_agent=child_agent,
        instruction=instruction,
        context=context,
    )


def make_supervisor_prepare(runtime: AgentRuntime, context_engine: ContextEngine | None = None):
    async def supervisor_prepare(state: dict) -> dict:
        emit_started(
            agent="supervisor_agent",
            stage="prepare",
            title="Supervisor Agent",
            summary="正在读取项目记忆、判断意图并冻结本轮子任务…",
        )
        route_fallback = _fallback_route(state)
        constraints_fallback = _fallback_brief(state)
        memory_fallback = _fallback_memory(state)
        fallback = {
            "memory": memory_fallback,
            "route": route_fallback["route"],
            "specialists": route_fallback["specialists"],
            "constraints": constraints_fallback,
            "style_bible": _fallback_direction(state),
            "audit_rules": ["保留锁定约束", "只合并已返回的专业结果", "修改基于当前选中版本"],
            "reason": route_fallback["reason"],
        }
        output, invocation = await runtime.call_json(
            state=state,
            agent="supervisor_agent",
            role="父级监督与任务规划 Agent",
            task=(
                "完成本轮父级规划：更新结构化 memory；判断 route=chat 或 generate；"
                "从 composition、subject、style 中选择最少必要 specialists；提取可验证 constraints；"
                "制定共享 style_bible 和 audit_rules。只做规划，不输出专业提案。"
            ),
            fallback=fallback,
            reason="一次性完成记忆、路由、Brief与美术方向规划",
        )
        route = output.get("route") if output.get("route") in {"chat", "generate"} else fallback["route"]
        specialists = _normalize_specialists(output.get("specialists"), route_fallback["specialists"])
        if route == "generate" and not specialists:
            specialists = ["composition_agent", "subject_agent", "style_agent"]

        candidate_memory = output.get("memory") if isinstance(output.get("memory"), dict) else memory_fallback
        memory = {key: candidate_memory.get(key, memory_fallback[key]) for key in MEMORY_KEYS}
        constraints = output.get("constraints") if isinstance(output.get("constraints"), dict) else constraints_fallback
        locked = list(dict.fromkeys([
            *state.get("locked_constraints", []),
            *constraints.get("locked_elements", []),
        ]))
        memory["locked_constraints"] = locked
        generated_style = output.get("style_bible") if isinstance(output.get("style_bible"), dict) else {}
        # 默认值补缺、模型结果居中、项目预设最终覆盖，保证硬风格约束优先。
        style_bible = {
            **fallback["style_bible"],
            **generated_style,
            **_preset_visual(state),
        }

        context_packet = state.get("context_packet", {})
        if context_engine is not None:
            try:
                context_packet = context_engine.memory_succeeded(state, memory)
            except Exception as exc:
                if bool(context_packet.get("compaction", {}).get("requested")):
                    context_engine.memory_failed(state, exc)
                else:
                    raise

        prepared_state = {
            **state,
            "memory": memory,
            "context_packet": context_packet,
            "routing": {
                "route": route,
                "specialists": specialists,
                "reason": str(output.get("reason") or fallback["reason"]),
            },
            "constraints": constraints,
            "locked_constraints": locked,
            "style_bible": style_bible,
            "audit_rules": list(output.get("audit_rules") or fallback["audit_rules"]),
        }
        tasks = (
            [
                _make_child_task(prepared_state, child, CHILD_INSTRUCTIONS[child]).model_dump()
                for child in specialists
            ]
            if route == "generate"
            else []
        )
        task_ids = [task["task_id"] for task in tasks]
        event = make_event(
            event_type="tasks_dispatched" if tasks else "agent_completed",
            agent="supervisor_agent",
            stage="prepare",
            status="completed",
            title="Supervisor Agent",
            summary=(
                f"已冻结并单向派发 {len(tasks)} 个隔离子任务。"
                if tasks
                else "本轮为普通讨论，不启动图像子任务。"
            ),
            payload={
                "route": route,
                "task_ids": task_ids,
                "child_agents": specialists,
                "dispatch_closed": True,
                "invocation_id": invocation["id"],
            },
        )
        return {
            "memory": memory,
            "context_packet": context_packet,
            "routing": prepared_state["routing"],
            "constraints": constraints,
            "locked_constraints": locked,
            "style_bible": style_bible,
            "audit_rules": prepared_state["audit_rules"],
            "child_tasks": tasks,
            "child_results": [],
            "expected_child_task_ids": task_ids,
            "dispatch_closed": True,
            "events": [event],
            "status": "briefing",
        }

    return supervisor_prepare


def make_supervisor_aggregate(runtime: AgentRuntime):
    async def supervisor_aggregate(state: dict) -> dict:
        emit_started(
            agent="supervisor_agent",
            stage="aggregate",
            title="Supervisor Agent",
            summary="全部子任务已返回，正在审核并合并结果…",
        )
        expected = set(state.get("expected_child_task_ids", []))
        results = [ChildResultEnvelope.model_validate(item) for item in state.get("child_results", [])]
        returned = {item.task_id for item in results}
        if returned != expected:
            missing = sorted(expected - returned)
            unexpected = sorted(returned - expected)
            raise RuntimeError(f"子任务屏障不完整：missing={missing}, unexpected={unexpected}")

        proposals = [
            {
                **item.proposal(),
                "task_id": item.task_id,
                # 保留旧版artifact协议字段，便于EventService和历史前端继续归档。
                "proposal_id": f"proposal_{item.task_id}",
                "agent": item.child_agent.removesuffix("_agent"),
                "attempt": 1,
                "child_status": item.status,
            }
            for item in results
        ]
        failed = [item for item in results if item.status != "completed"]
        fragments = [item.get("prompt_fragment", "") for item in proposals if item.get("prompt_fragment")]
        fallback = {
            "selected_parts": {
                item["agent"]: {
                    "task_id": item["task_id"],
                    "reason": "子任务已通过父级结果屏障",
                    "prompt_fragment": item.get("prompt_fragment", ""),
                }
                for item in proposals
            },
            "rationale": "仅合并本轮冻结任务返回的结果，并保留未修改维度。",
            "discarded": [],
            "unresolved_risks": [f"{item.child_agent}: {item.error or item.status}" for item in failed],
            "final_prompt_plan": {
                "base_request": state.get("user_request", ""),
                "preserve": state.get("locked_constraints", []),
                "specialist_fragments": fragments,
                "style_bible": state.get("style_bible", {}),
            },
        }
        output, invocation = await runtime.call_json(
            state={
                **state,
                "recent_messages": [{"isolated_child_results": proposals}],
            },
            agent="supervisor_agent",
            role="父级监督与结果汇聚 Agent",
            task=(
                "全部子任务已经结束。审核返回结果与硬约束的一致性，处理冲突并输出"
                "selected_parts、rationale、discarded、unresolved_risks、final_prompt_plan。"
                "只能使用收到的子结果，不得假设子 Agent 的隐藏推理。"
            ),
            fallback=fallback,
            reason="等待全部子消息后执行唯一一次父级合并",
        )
        selected = {**fallback, **output}
        event = make_event(
            event_type="children_aggregated",
            agent="supervisor_agent",
            stage="aggregate",
            status="completed",
            title="Supervisor Agent",
            summary=f"已收齐并处理 {len(results)}/{len(expected)} 个子任务结果。",
            payload={
                "expected_task_ids": sorted(expected),
                "received_task_ids": sorted(returned),
                "failed_count": len(failed),
                "invocation_id": invocation["id"],
            },
        )
        return {
            "proposals": proposals,
            "selected_concept": selected,
            "events": [event],
            "status": "curating",
        }

    return supervisor_aggregate


def make_supervisor_finalize(runtime: AgentRuntime):
    async def supervisor_finalize(state: dict) -> dict:
        emit_started(
            agent="supervisor_agent",
            stage="response",
            title="Supervisor Agent",
            summary="正在整理本轮结果与下一步建议…",
        )
        count = len(state.get("candidate_images", []))
        route = state.get("routing", {}).get("route", "generate")
        fallback_message = (
            f"已生成 {count} 张新候选图。你可以先选择一张，再继续说明局部修改方向。"
            if count
            else "我已结合当前项目记忆完成本轮回复；如需继续出图，请直接描述要修改的视觉部分。"
        )
        output, invocation = await runtime.call_json(
            state=state,
            agent="supervisor_agent",
            role="父级监督与用户沟通 Agent",
            task=(
                f"本轮 route={route}，生成图片数={count}。输出 JSON："
                '{"message":"简洁中文回复"}。说明完成内容并给出一个自然的下一步。'
            ),
            fallback={"message": fallback_message},
            reason="父 Agent 在全部执行完成后统一回复用户",
        )
        message = str(output.get("message") or fallback_message)[:1000]
        event = make_event(
            event_type="agent_completed",
            agent="supervisor_agent",
            stage="response",
            status="completed",
            title="Supervisor Agent",
            summary="本轮父级流程已完成。",
            payload={"message": message, "invocation_id": invocation["id"]},
        )
        return {"assistant_message": message, "events": [event], "status": "completed"}

    return supervisor_finalize
