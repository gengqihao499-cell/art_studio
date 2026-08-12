"""ArtFlow 5-Agent LangGraph主图。

活跃逻辑Agent：Supervisor、Composition、Subject、Style、Image。
三个专业子Agent在私有子图中并行运行；父级只在全部终态消息进入屏障后恢复。
旧版细粒度 Agent 已移除，避免未注册代码与真实运行链路产生歧义。
"""

from __future__ import annotations

import os

from langgraph.graph import END, START, StateGraph

from app.agents.common import AgentRuntime
from app.agents.image_agent import make_image_agent
from app.agents.parallel_specialists import make_parallel_specialists
from app.agents.supervisor_agent import (
    make_supervisor_aggregate,
    make_supervisor_finalize,
    make_supervisor_prepare,
)
from app.schemas.art_state import ArtDesignState


def _route_after_prepare(state: dict) -> str:
    return (
        "supervisor_finalize"
        if state.get("routing", {}).get("route") == "chat"
        else "parallel_specialists"
    )


class ArtDesignGraph:
    def __init__(
        self,
        checkpointer,
        image_backend,
        chat_provider,
        agent_logs,
        context_engine=None,
    ) -> None:
        runtime = AgentRuntime(chat_provider, agent_logs, context_engine)
        builder = StateGraph(ArtDesignState)

        # 同一个Supervisor分三个阶段出现，但逻辑身份、日志名称和职责边界一致。
        builder.add_node(
            "supervisor_prepare",
            make_supervisor_prepare(runtime, context_engine),
        )
        builder.add_node(
            "parallel_specialists",
            make_parallel_specialists(
                runtime,
                timeout_seconds=float(
                    os.getenv("ARTFLOW_CHILD_TIMEOUT_SECONDS", "90")
                ),
            ),
        )
        builder.add_node("supervisor_aggregate", make_supervisor_aggregate(runtime))
        builder.add_node(
            "image_agent",
            make_image_agent(runtime, image_backend, agent_logs),
        )
        builder.add_node("supervisor_finalize", make_supervisor_finalize(runtime))

        builder.add_edge(START, "supervisor_prepare")
        builder.add_conditional_edges(
            "supervisor_prepare",
            _route_after_prepare,
            {
                "parallel_specialists": "parallel_specialists",
                "supervisor_finalize": "supervisor_finalize",
            },
        )
        # parallel_specialists内部使用三个ChildGraphState私有子图并行执行。
        # 该节点只有收齐全部completed/failed/timed_out结果后才会返回。
        builder.add_edge("parallel_specialists", "supervisor_aggregate")
        builder.add_edge("supervisor_aggregate", "image_agent")
        builder.add_edge("image_agent", "supervisor_finalize")
        builder.add_edge("supervisor_finalize", END)

        self.compiled = builder.compile(checkpointer=checkpointer)
