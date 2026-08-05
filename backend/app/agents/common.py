from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from langgraph.config import get_stream_writer

from app.providers.base import ChatProvider

if TYPE_CHECKING:
    from app.context import ContextEngine
    from app.services.agent_log_service import AgentLogService


AGENTS = ("composition", "character", "color")


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


def latest_by_agent(items: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for item in items:
        agent = item["agent"]
        if agent not in latest or item.get("attempt", 0) >= latest[agent].get("attempt", 0):
            latest[agent] = item
    return latest


def revision_for(state: dict, agent: str) -> list[str]:
    review = latest_by_agent(state.get("reviews", [])).get(agent)
    if not review or review.get("approved"):
        return []
    return list(review.get("revision_instructions", []))


def next_attempt(state: dict, agent: str) -> int:
    return int(state.get("attempts", {}).get(agent, 0)) + 1
