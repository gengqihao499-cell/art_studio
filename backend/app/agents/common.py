from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from langgraph.config import get_stream_writer

from app.providers.base import ChatProvider
from app.schemas.agent_protocol import ChildTaskEnvelope

if TYPE_CHECKING:
    from app.context import ContextEngine
    from app.services.agent_log_service import AgentLogService


class AgentRuntime:
    """Shared provider/logging boundary used by every real text Agent."""

    def __init__(
        self,
        provider: ChatProvider,
        logs: AgentLogService,
        context_engine: ContextEngine | None = None,
    ) -> None:
        self.provider = provider
        self.logs = logs
        self.context_engine = context_engine

    async def call_json(
        self,
        *,
        state: dict,
        agent: str,
        role: str,
        task: str,
        fallback: dict,
        attempt: int = 1,
        reason: str = "",
    ) -> tuple[dict, dict]:
        system_prompt = (
            f"你是 ArtFlow Studio 的 {role}。只处理本 Agent 职责，不替其他 Agent 做决定。"
            "必须只输出一个合法 JSON 对象，不要 Markdown，不要解释。"
        )
        # Context Collapse happens at read time. Each Agent receives the same
        # canonical state but a smaller role-specific projection.
        context = (
            self.context_engine.project_for_agent(state, agent)
            if self.context_engine
            else {
                "current_request": state.get("user_request", ""),
                "world_context": state.get("world_context", ""),
                "memory": state.get("memory", {}),
                "recent_messages": state.get("recent_messages", []),
                "locked_constraints": state.get("locked_constraints", []),
                "selected_image": state.get("parent_image", {}),
            }
        )
        user_prompt = f"任务：{task}\n上下文：{json.dumps(context, ensure_ascii=False)}"
        try:
            output, result = await self.provider.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                fallback=fallback,
            )
            invocation = self.logs.record(
                state=state,
                agent=agent,
                status="completed",
                model=result.model,
                input_text=user_prompt,
                output_text=result.content,
                structured_output=output,
                result=result,
                attempt=attempt,
                reason=reason,
            )
            return output, invocation
        except Exception as exc:
            self.logs.record(
                state=state,
                agent=agent,
                status="failed",
                model=self.provider.model,
                input_text=user_prompt,
                attempt=attempt,
                reason=reason,
                error=exc,
            )
            raise

    async def call_isolated_json(
        self,
        *,
        task_envelope: ChildTaskEnvelope,
        role: str,
        task: str,
        fallback: dict,
        attempt: int = 1,
        reason: str = "",
    ) -> tuple[dict, dict]:
        """在严格隔离的子任务上下文中调用模型。

        与 ``call_json`` 不同，本方法不接受父图 State，也不会调用
        ContextProjector。子 Agent 能看到的全部内容只能来自已校验的任务信封。
        """

        system_prompt = (
            f"你是 ArtFlow Studio 的{role}。只处理任务信封指定的职责，"
            "不得推测或请求父 Agent、其他子 Agent 的隐藏上下文。"
            "只输出一个合法 JSON 对象，不要输出 Markdown 或解释。"
        )
        isolated_context = task_envelope.context()
        user_prompt = (
            f"task_id={task_envelope.task_id}\n"
            f"任务：{task}\n"
            f"隔离上下文：{json.dumps(isolated_context, ensure_ascii=False)}"
        )
        log_state = task_envelope.log_state()
        agent = task_envelope.child_agent
        try:
            output, result = await self.provider.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                fallback=fallback,
            )
            invocation = self.logs.record(
                state=log_state,
                agent=agent,
                status="completed",
                model=result.model,
                input_text=user_prompt,
                output_text=result.content,
                structured_output={
                    "task_id": task_envelope.task_id,
                    "parent_run_id": task_envelope.parent_run_id,
                    "result": output,
                },
                result=result,
                attempt=attempt,
                reason=reason,
            )
            return output, invocation
        except Exception as exc:
            self.logs.record(
                state=log_state,
                agent=agent,
                status="failed",
                model=self.provider.model,
                input_text=user_prompt,
                structured_output={
                    "task_id": task_envelope.task_id,
                    "parent_run_id": task_envelope.parent_run_id,
                },
                attempt=attempt,
                reason=reason,
                error=exc,
            )
            raise

    def skip(self, *, state: dict, agent: str, reason: str) -> dict:
        return self.logs.record(
            state=state,
            agent=agent,
            status="skipped",
            model=self.provider.model,
            input_text=state.get("user_request", ""),
            output_text="本轮跳过",
            reason=reason,
        )


def make_event(
    *,
    event_type: str,
    agent: str,
    stage: str,
    status: str,
    title: str,
    summary: str,
    attempt: int = 1,
    payload: dict | None = None,
) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "event_type": event_type,
        "agent": agent,
        "stage": stage,
        "status": status,
        "attempt": attempt,
        "title": title,
        "summary": summary,
        "payload": payload or {},
        "created_at": datetime.now(UTC).isoformat(),
    }


def emit_started(
    *,
    agent: str,
    stage: str,
    title: str,
    summary: str,
    attempt: int = 1,
) -> None:
    event = make_event(
        event_type="agent_started" if attempt == 1 else "agent_retrying",
        agent=agent,
        stage=stage,
        status="running",
        title=title,
        summary=summary,
        attempt=attempt,
    )
    try:
        get_stream_writer()(event)
    except RuntimeError:
        # Direct unit calls do not have a LangGraph streaming context.
        pass
