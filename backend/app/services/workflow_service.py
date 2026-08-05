import traceback
import uuid

from app.agents.common import make_event
from app.context import LoopCircuitOpen, LoopGuard
from app.services.event_service import EventService
from app.services.project_service import ProjectService


class WorkflowService:
    def __init__(
        self,
        project_service: ProjectService,
        event_service: EventService,
    ) -> None:
        self.project_service = project_service
        self.event_service = event_service
        self.graph = None

    def set_graph(self, graph) -> None:
        self.graph = graph

    async def execute(self, initial_state: dict) -> None:
        await self._execute(
            initial_state["run_id"], initial_state["project_id"], initial_state
        )

    async def resume(self, run_id: str, project_id: str) -> None:
        self.event_service.append(
            project_id,
            run_id,
            [
                make_event(
                    event_type="agent_retrying",
                    agent="image_worker",
                    stage="generation",
                    status="running",
                    title="Image Worker",
                    summary="正在从最后一个 LangGraph checkpoint 恢复失败任务…",
                )
            ],
        )
        await self._execute(run_id, project_id, None)

    async def _execute(
        self,
        run_id: str,
        project_id: str,
        graph_input: dict | None,
    ) -> None:
        config = {
            "configurable": {"thread_id": run_id},
            "recursion_limit": 25,
            "max_concurrency": 3,
        }
        loop_guard = LoopGuard(max_same_signature=3, max_node_visits=4)
        try:
            if self.graph is None:
                raise RuntimeError("ArtDesignGraph is not initialized")
            async for mode, chunk in self.graph.astream(
                graph_input,
                config,
                stream_mode=["updates", "custom"],
            ):
                if mode == "custom":
                    self.event_service.append(project_id, run_id, [chunk])
                    continue
                if mode != "updates" or not isinstance(chunk, dict):
                    continue
                for node_name, update in chunk.items():
                    if not isinstance(update, dict):
                        continue
                    loop_guard.observe(str(node_name), update)
                    self.event_service.append(
                        project_id, run_id, update.get("events", [])
                    )
                    self.event_service.append_artifacts(project_id, run_id, update)

            snapshot = await self.graph.aget_state(config)
            self.project_service.complete_agent_run(run_id, dict(snapshot.values))
        except Exception as exc:
            self.project_service.fail_agent_run(run_id, str(exc))
            circuit_open = isinstance(exc, LoopCircuitOpen)
            self.event_service.append(
                project_id,
                run_id,
                [
                    {
                        "id": f"evt_failed_{uuid.uuid4().hex[:12]}",
                        "event_type": "circuit_opened" if circuit_open else "run_failed",
                        "agent": "orchestrator",
                        "stage": "system",
                        "status": "failed",
                        "attempt": 1,
                        "title": "Agent workflow failed",
                        "summary": str(exc),
                        "payload": {
                            "retryable": not circuit_open,
                            "traceback": traceback.format_exc(limit=5),
                        },
                    }
                ],
            )
