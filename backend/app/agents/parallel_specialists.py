"""三个专业子 Agent 的私有子图与并行结果屏障。"""

from __future__ import annotations

import asyncio
import json
import time

from langgraph.graph import END, START, StateGraph

from app.agents.common import AgentRuntime, emit_started, make_event
from app.agents.edit_intent import extract_removal_target, is_character_target, is_remove_request
from app.schemas.agent_protocol import ChildGraphState, ChildResultEnvelope, ChildTaskEnvelope


SPECIALIST_CONFIG = {
    "composition_agent": {
        "title": "Composition Agent",
        "role": "构图专业子 Agent",
        "task": "只输出 summary、decisions、constraints_addressed、prompt_fragment。处理镜头、构图、主体占比和空间层次。",
        "fallback": {
            "summary": "保持主体关系，按本轮要求调整镜头和空间层次。",
            "decisions": {
                "camera": "purposeful game-concept framing",
                "subject_coverage": 0.65,
                "depth_layers": 3,
            },
            "constraints_addressed": ["hc_request"],
            "prompt_fragment": "purposeful composition, readable subject placement, clear foreground midground background",
        },
    },
    "subject_agent": {
        "title": "Subject Agent",
        "role": "主体与道具专业子 Agent",
        "task": "只输出 summary、decisions、constraints_addressed、prompt_fragment。处理角色、道具、姿态、轮廓、身份连续性和对象删除。",
        "fallback": {
            "summary": "保持主体身份与锁定特征，只调整本轮明确要求的主体内容。",
            "decisions": {
                "identity_continuity": True,
                "silhouette": "清晰的游戏主体轮廓",
                "locked_features_preserved": True,
            },
            "constraints_addressed": ["hc_request"],
            "prompt_fragment": "保持主体身份一致、结构与轮廓清晰，并保留锁定特征",
        },
    },
    "style_agent": {
        "title": "Style Agent",
        "role": "画风、色彩与光照专业子 Agent",
        "task": "只输出 summary、decisions、constraints_addressed、prompt_fragment。处理画风、色板、光照、材质和明暗分离。",
        "fallback": {
            "summary": "延续项目画风，按本轮要求调整色板、光照与材质响应。",
            "decisions": {
                "value_separation": "clear",
                "focal_accent": "controlled",
                "material_response": "coherent",
            },
            "constraints_addressed": ["hc_request"],
            "prompt_fragment": "coherent art style and palette, controlled focal lighting, clear value separation",
        },
    },
}


def _subject_fallback(envelope: ChildTaskEnvelope, base: dict) -> dict:
    """对象删除属于Subject职责，保留已有的强制删除语义。"""

    context = envelope.context()
    request = str(context.get("current_request") or "")
    target = extract_removal_target(request) if is_remove_request(request) else ""
    if not target or not is_character_target(target, request):
        return base
    return {
        "summary": f"完整移除{target}，不保留替代角色。",
        "decisions": {
            "character_present": False,
            "identity_continuity": False,
            "background_inpaint_required": True,
        },
        "constraints_addressed": ["hc_request"],
        "prompt_fragment": (
            f"完整移除{target}及其轮廓、阴影、倒影和随身物，"
            "自然补全被遮挡背景，不加入替代人物或生物"
        ),
    }


def _make_child_node(runtime: AgentRuntime, expected_agent: str):
    config = SPECIALIST_CONFIG[expected_agent]

    async def child_node(state: ChildGraphState) -> dict:
        envelope = ChildTaskEnvelope.model_validate(state["task"])
        if envelope.child_agent != expected_agent:
            raise ValueError(
                f"子图职责不匹配：expected={expected_agent}, actual={envelope.child_agent}"
            )
        emit_started(
            agent=expected_agent,
            stage="isolated_task",
            title=config["title"],
            summary=f"正在执行隔离任务 {envelope.task_id}…",
        )
        started = time.perf_counter()
        fallback = dict(config["fallback"])
        if expected_agent == "subject_agent":
            fallback = _subject_fallback(envelope, fallback)
        invocation_id = ""
        error = ""
        status = "completed"
        try:
            output, invocation = await runtime.call_isolated_json(
                task_envelope=envelope,
                role=config["role"],
                task=f"{envelope.instruction}\n{config['task']}",
                fallback=fallback,
                reason=f"执行父任务 {envelope.parent_run_id} 派发的冻结任务 {envelope.task_id}",
            )
            proposal = {**fallback, **output}
            invocation_id = invocation["id"]
        except Exception as exc:
            # 子任务失败也必须返回结果信封，让父级等待其他任务后统一决策。
            proposal = fallback
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"[:1000]
        result = ChildResultEnvelope(
            task_id=envelope.task_id,
            parent_run_id=envelope.parent_run_id,
            child_agent=envelope.child_agent,
            status=status,
            proposal_json=json.dumps(proposal, ensure_ascii=False),
            error=error,
            latency_ms=int((time.perf_counter() - started) * 1000),
            invocation_id=invocation_id,
        )
        event = make_event(
            event_type="child_completed" if status == "completed" else "child_failed",
            agent=expected_agent,
            stage="isolated_task",
            status=status,
            title=config["title"],
            summary=(
                f"隔离任务 {envelope.task_id} 已完成。"
                if status == "completed"
                else f"隔离任务 {envelope.task_id} 失败，已返回降级结果。"
            ),
            payload={
                "task_id": envelope.task_id,
                "parent_run_id": envelope.parent_run_id,
                "context_sha256": envelope.context_sha256,
                "invocation_id": invocation_id,
            },
        )
        return {"result": result.model_dump(), "events": [event]}

    return child_node


def _compile_child_graph(runtime: AgentRuntime, child_agent: str):
    """每个专业Agent拥有独立StateGraph和ChildGraphState。"""

    builder = StateGraph(ChildGraphState)
    builder.add_node(child_agent, _make_child_node(runtime, child_agent))
    builder.add_edge(START, child_agent)
    builder.add_edge(child_agent, END)
    return builder.compile()


def make_parallel_specialists(runtime: AgentRuntime, timeout_seconds: float = 90.0):
    child_graphs = {
        agent: _compile_child_graph(runtime, agent)
        for agent in SPECIALIST_CONFIG
    }

    async def parallel_specialists(state: dict) -> dict:
        if not state.get("dispatch_closed"):
            raise RuntimeError("父任务尚未关闭派发阶段，禁止启动子 Agent")
        envelopes = [ChildTaskEnvelope.model_validate(item) for item in state.get("child_tasks", [])]
        expected = set(state.get("expected_child_task_ids", []))
        actual = {item.task_id for item in envelopes}
        if expected != actual:
            raise RuntimeError(f"派发任务不完整：expected={sorted(expected)}, actual={sorted(actual)}")

        emit_started(
            agent="supervisor_agent",
            stage="waiting",
            title="Supervisor Agent",
            summary=f"已停止派发，正在等待 {len(envelopes)} 个并行子任务全部返回…",
        )

        async def run_one(envelope: ChildTaskEnvelope) -> tuple[dict, list[dict]]:
            graph = child_graphs[envelope.child_agent]
            try:
                output = await asyncio.wait_for(
                    graph.ainvoke({"task": envelope.model_dump()}),
                    timeout=timeout_seconds,
                )
                return output["result"], list(output.get("events", []))
            except TimeoutError:
                result = ChildResultEnvelope(
                    task_id=envelope.task_id,
                    parent_run_id=envelope.parent_run_id,
                    child_agent=envelope.child_agent,
                    status="timed_out",
                    error=f"子任务超过 {timeout_seconds:g} 秒",
                ).model_dump()
                event = make_event(
                    event_type="child_timed_out",
                    agent=envelope.child_agent,
                    stage="isolated_task",
                    status="timed_out",
                    title=SPECIALIST_CONFIG[envelope.child_agent]["title"],
                    summary=f"隔离任务 {envelope.task_id} 超时，已形成失败回执。",
                    payload={"task_id": envelope.task_id, "parent_run_id": envelope.parent_run_id},
                )
                return result, [event]

        # return_exceptions=True保证某个子图的框架级异常不会提前取消其他子图。
        # 父Agent只有在每个任务都成功、失败或超时后才会恢复。
        raw_completed = await asyncio.gather(
            *(run_one(envelope) for envelope in envelopes),
            return_exceptions=True,
        )
        completed: list[tuple[dict, list[dict]]] = []
        for envelope, item in zip(envelopes, raw_completed, strict=True):
            if not isinstance(item, BaseException):
                completed.append(item)
                continue
            result = ChildResultEnvelope(
                task_id=envelope.task_id,
                parent_run_id=envelope.parent_run_id,
                child_agent=envelope.child_agent,
                status="failed",
                error=f"{type(item).__name__}: {item}"[:1000],
            ).model_dump()
            event = make_event(
                event_type="child_failed",
                agent=envelope.child_agent,
                stage="isolated_task",
                status="failed",
                title=SPECIALIST_CONFIG[envelope.child_agent]["title"],
                summary=f"隔离任务 {envelope.task_id} 出现框架异常，已形成失败回执。",
                payload={"task_id": envelope.task_id, "parent_run_id": envelope.parent_run_id},
            )
            completed.append((result, [event]))
        results = [item[0] for item in completed]
        child_events = [event for item in completed for event in item[1]]
        barrier_event = make_event(
            event_type="all_children_joined",
            agent="supervisor_agent",
            stage="waiting",
            status="completed",
            title="Supervisor Agent",
            summary=f"并行屏障已收齐 {len(results)}/{len(envelopes)} 个终态消息。",
            payload={
                "expected_task_ids": [item.task_id for item in envelopes],
                "received_task_ids": [item["task_id"] for item in results],
                "parent_intervention_allowed": False,
            },
        )
        return {"child_results": results, "events": [*child_events, barrier_event]}

    return parallel_specialists
