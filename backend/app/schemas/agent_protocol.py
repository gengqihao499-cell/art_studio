"""父子 Agent 的单向通信协议。

子 Agent 只接收序列化后的不可变任务信封，不接触父图的完整 State。
任务上下文保存为带 SHA256 校验的 JSON 字符串，子 Agent 每次读取都会得到
新的对象副本，避免并行任务通过可变引用互相污染。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator


ChildAgentName = Literal["composition_agent", "subject_agent", "style_agent"]
ChildStatus = Literal["completed", "failed", "timed_out"]


def _canonical_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ChildTaskEnvelope(BaseModel):
    """Supervisor 在派发前一次性创建的不可变子任务。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    parent_run_id: str
    project_id: str
    session_id: str = ""
    turn_id: str = ""
    child_agent: ChildAgentName
    instruction: str
    context_json: str
    context_sha256: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        parent_run_id: str,
        project_id: str,
        session_id: str,
        turn_id: str,
        child_agent: ChildAgentName,
        instruction: str,
        context: dict,
    ) -> "ChildTaskEnvelope":
        serialized = _canonical_json(context)
        return cls(
            task_id=task_id,
            parent_run_id=parent_run_id,
            project_id=project_id,
            session_id=session_id,
            turn_id=turn_id,
            child_agent=child_agent,
            instruction=instruction,
            context_json=serialized,
            context_sha256=_sha256(serialized),
        )

    @model_validator(mode="after")
    def validate_context_hash(self) -> "ChildTaskEnvelope":
        if _sha256(self.context_json) != self.context_sha256:
            raise ValueError("子任务上下文校验失败")
        return self

    def context(self) -> dict:
        """返回新的上下文副本，不暴露父状态中的可变对象。"""

        value = json.loads(self.context_json)
        if not isinstance(value, dict):
            raise ValueError("子任务上下文必须是 JSON 对象")
        return value

    def log_state(self) -> dict:
        """生成 AgentLogService 所需的最小运行元数据。"""

        return {
            "project_id": self.project_id,
            "session_id": self.session_id or None,
            "turn_id": self.turn_id or None,
            "run_id": self.parent_run_id,
        }


class ChildResultEnvelope(BaseModel):
    """子 Agent 完成后返回的只读结果；父 Agent 是唯一合并方。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    parent_run_id: str
    child_agent: ChildAgentName
    status: ChildStatus
    proposal_json: str = "{}"
    error: str = ""
    latency_ms: int = 0
    invocation_id: str = ""
    completed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def proposal(self) -> dict:
        value = json.loads(self.proposal_json or "{}")
        return value if isinstance(value, dict) else {}


class ChildGraphState(TypedDict, total=False):
    """独立子图的全部状态，不包含父图会话、记忆或其他 Agent 结果。"""

    task: dict
    result: dict
    events: list[dict]
