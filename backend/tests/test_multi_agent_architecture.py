"""5-Agent父子隔离、并行屏障和单向通信测试。"""

from __future__ import annotations

import asyncio
import copy
import json
import time
import unittest

from app.agents.common import AgentRuntime
from app.agents.parallel_specialists import make_parallel_specialists
from app.agents.supervisor_agent import _make_child_task
from app.graph.art_design_graph import ArtDesignGraph
from app.providers.mock_chat_provider import MockChatProvider
from app.providers.base import ChatResult
from app.schemas.agent_protocol import ChildTaskEnvelope


class CapturingLogs:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, **kwargs) -> dict:
        row = {**kwargs, "id": f"inv_test_{len(self.rows) + 1}"}
        self.rows.append(row)
        return row


class DelayedProvider:
    name = "delayed-test"
    model = "delayed-test-model"

    def __init__(self, default_delay: float = 0.08, style_delay: float | None = None) -> None:
        self.default_delay = default_delay
        self.style_delay = style_delay
        self.calls: list[dict] = []

    async def complete_json(self, *, system_prompt: str, user_prompt: str, fallback: dict):
        delay = (
            self.style_delay
            if self.style_delay is not None and "画风、色彩" in system_prompt
            else self.default_delay
        )
        started = time.perf_counter()
        self.calls.append({"system": system_prompt, "user": user_prompt, "started": started})
        await asyncio.sleep(delay)
        content = json.dumps(fallback, ensure_ascii=False)
        return fallback, ChatResult(
            content=content,
            model=self.model,
            latency_ms=int(delay * 1000),
        )


def make_envelope(agent: str, index: int) -> ChildTaskEnvelope:
    return ChildTaskEnvelope.create(
        task_id=f"task_{index}",
        parent_run_id="run_test",
        project_id="project_test",
        session_id="session_test",
        turn_id="turn_test",
        child_agent=agent,
        instruction=f"执行{agent}职责",
        context={
            "current_request": "设计一个月下像素场景",
            "constraints": {"locked_elements": ["像素画"]},
            "memory": {"project_goal": "像素游戏美术"},
        },
    )


class MultiAgentArchitectureTests(unittest.TestCase):
    def test_child_task_is_frozen_and_context_is_copy(self):
        envelope = make_envelope("composition_agent", 1)
        first = envelope.context()
        first["memory"]["project_goal"] = "被子任务修改"
        second = envelope.context()
        self.assertEqual(second["memory"]["project_goal"], "像素游戏美术")
        with self.assertRaises(Exception):
            envelope.task_id = "changed"

    def test_supervisor_allowlist_hides_parent_and_sibling_context(self):
        parent = {
            "run_id": "run_test",
            "project_id": "project_test",
            "session_id": "session_test",
            "turn_id": "turn_test",
            "user_request": "调整构图",
            "world_context": "月下森林",
            "constraints": {},
            "locked_constraints": ["像素画"],
            "style_bible": {},
            "parent_image": {},
            "reference_images": [],
            "version_number": 2,
            "memory": {
                "project_goal": "像素游戏",
                "locked_constraints": ["像素画"],
                "composition_facts": ["横版镜头"],
                "character_facts": ["不应泄漏的角色秘密"],
                "style_decisions": ["不应泄漏的色彩秘密"],
                "active_image": {},
            },
            "recent_messages": [{"content": "不应泄漏的完整对话"}],
            "context_packet": {"claude_md": "不应泄漏的父级记忆"},
            "proposals": [{"secret": "不应泄漏的兄弟结果"}],
        }
        envelope = _make_child_task(parent, "composition_agent", "只处理构图")
        context = envelope.context()
        serialized = envelope.context_json
        self.assertEqual(set(context["memory"]), {
            "project_goal", "locked_constraints", "composition_facts", "active_image"
        })
        for hidden in ("完整对话", "父级记忆", "兄弟结果", "角色秘密", "色彩秘密"):
            self.assertNotIn(hidden, serialized)

    def test_children_run_concurrently_and_barrier_returns_all(self):
        provider = DelayedProvider(default_delay=0.12)
        runtime = AgentRuntime(provider, CapturingLogs())
        parallel = make_parallel_specialists(runtime, timeout_seconds=1.0)
        envelopes = [
            make_envelope("composition_agent", 1),
            make_envelope("subject_agent", 2),
            make_envelope("style_agent", 3),
        ]
        state = {
            "dispatch_closed": True,
            "child_tasks": [item.model_dump() for item in envelopes],
            "expected_child_task_ids": [item.task_id for item in envelopes],
        }
        original = copy.deepcopy(state)
        started = time.perf_counter()
        update = asyncio.run(parallel(state))
        elapsed = time.perf_counter() - started
        self.assertEqual(len(update["child_results"]), 3)
        self.assertTrue(all(item["status"] == "completed" for item in update["child_results"]))
        self.assertLess(elapsed, 0.28, "三个0.12秒任务不应按0.36秒串行执行")
        self.assertLess(max(call["started"] for call in provider.calls) - min(call["started"] for call in provider.calls), 0.08)
        self.assertEqual(state, original, "并行子图不得原地修改父状态")
        self.assertEqual(update["events"][-1]["event_type"], "all_children_joined")

    def test_timeout_does_not_cancel_siblings_and_parent_waits_for_all(self):
        provider = DelayedProvider(default_delay=0.01, style_delay=0.12)
        runtime = AgentRuntime(provider, CapturingLogs())
        parallel = make_parallel_specialists(runtime, timeout_seconds=0.05)
        envelopes = [
            make_envelope("composition_agent", 1),
            make_envelope("subject_agent", 2),
            make_envelope("style_agent", 3),
        ]
        state = {
            "dispatch_closed": True,
            "child_tasks": [item.model_dump() for item in envelopes],
            "expected_child_task_ids": [item.task_id for item in envelopes],
        }
        started = time.perf_counter()
        update = asyncio.run(parallel(state))
        elapsed = time.perf_counter() - started
        statuses = {item["child_agent"]: item["status"] for item in update["child_results"]}
        self.assertEqual(statuses["composition_agent"], "completed")
        self.assertEqual(statuses["subject_agent"], "completed")
        self.assertEqual(statuses["style_agent"], "timed_out")
        self.assertEqual(len(update["child_results"]), 3)
        self.assertGreaterEqual(elapsed, 0.045, "父级不能在慢任务进入终态前恢复")

    def test_children_cannot_start_before_dispatch_is_closed(self):
        runtime = AgentRuntime(DelayedProvider(default_delay=0), CapturingLogs())
        parallel = make_parallel_specialists(runtime, timeout_seconds=1)
        with self.assertRaisesRegex(RuntimeError, "尚未关闭派发阶段"):
            asyncio.run(parallel({"dispatch_closed": False, "child_tasks": []}))

    def test_full_five_agent_graph_runs_end_to_end(self):
        class EmptyImageBackend:
            name = "mock"

            async def generate(self, request):
                return []

        logs = CapturingLogs()
        graph = ArtDesignGraph(
            None,
            EmptyImageBackend(),
            MockChatProvider(),
            logs,
            None,
        ).compiled
        initial_state = {
            "thread_id": "run_graph_test",
            "run_id": "run_graph_test",
            "project_id": "project_test",
            "project_name": "测试项目",
            "session_id": "session_test",
            "turn_id": "turn_test",
            "turn_sequence": 1,
            "version_number": 1,
            "user_request": "设计一个月下森林像素游戏场景",
            "reference_images": [],
            "world_context": "横版像素沙盒游戏",
            "aspect_ratio": "1:1",
            "image_count": 4,
            "image_backend": "mock",
            "image_model": "test-image-model",
            "parent_image": {},
            "recent_messages": [],
            "context_packet": {},
            "memory": {},
            "locked_constraints": [],
            "style_profile": {"style_bible": {}},
            "proposals": [],
            "reviews": [],
            "events": [],
            "attempts": {},
        }
        result = asyncio.run(
            graph.ainvoke(
                initial_state,
                {"configurable": {"thread_id": "run_graph_test"}},
            )
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["child_results"]), 3)
        self.assertTrue(all(item.get("proposal_id") for item in result["proposals"]))
        self.assertTrue(all(item.get("attempt") == 1 for item in result["proposals"]))
        self.assertTrue(result["assistant_message"])
        active_agents = {row["agent"] for row in logs.rows}
        self.assertEqual(
            active_agents,
            {
                "supervisor_agent",
                "composition_agent",
                "subject_agent",
                "style_agent",
                "image_agent",
            },
        )


if __name__ == "__main__":
    unittest.main()
