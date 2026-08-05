"""LangGraph orchestration for the ArtFlow multi-Agent backend.

The file intentionally exposes the architectural boundaries in comments so a
developer can see which nodes are independent Agents and where combination occurs.
"""

from langgraph.graph import END, START, StateGraph

from app.agents.art_director import make_art_director, make_review_agent
from app.agents.assistant_agent import make_assistant_agent
from app.agents.brief_agent import make_brief_agent
from app.agents.character_agent import make_character_agent
from app.agents.color_agent import make_color_agent
from app.agents.common import AgentRuntime
from app.agents.composition_agent import make_composition_agent
from app.agents.curator_agent import make_curator_agent
from app.agents.image_worker import make_image_worker
from app.agents.intent_router import make_intent_router
from app.agents.memory_agent import make_memory_agent
from app.agents.workflow_compiler import make_prompt_compiler
from app.schemas.art_state import ArtDesignState


def _route_after_intent(state: dict) -> str:
    return "assistant_agent" if state.get("routing", {}).get("route") == "chat" else "brief_agent"


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

        # 1) AGENT REGISTRATION — each node has one explicit responsibility.
        builder.add_node("memory_agent", make_memory_agent(runtime, context_engine))
        builder.add_node("intent_router", make_intent_router(runtime))
        builder.add_node("brief_agent", make_brief_agent(runtime))
        builder.add_node("art_director", make_art_director(runtime))
        builder.add_node("composition_agent", make_composition_agent(runtime))
        builder.add_node("character_agent", make_character_agent(runtime))
        builder.add_node("color_agent", make_color_agent(runtime))
        builder.add_node("art_director_review", make_review_agent(runtime))
        builder.add_node("curator", make_curator_agent(runtime))
        builder.add_node("prompt_compiler", make_prompt_compiler(runtime))
        builder.add_node("image_worker", make_image_worker(image_backend, agent_logs))
        builder.add_node("assistant_agent", make_assistant_agent(runtime))

        # 2) CONTEXT + ROUTING — chat-only turns never call image generation.
        builder.add_edge(START, "memory_agent")
        builder.add_edge("memory_agent", "intent_router")
        builder.add_conditional_edges("intent_router", _route_after_intent)
        builder.add_edge("brief_agent", "art_director")

        # 3) PARALLEL SPECIALISTS — unselected nodes log “本轮跳过” without an LLM call.
        for specialist in ("composition_agent", "character_agent", "color_agent"):
            builder.add_edge("art_director", specialist)
            builder.add_edge(specialist, "art_director_review")

        # 4) COMBINATION BOUNDARY — only Curator combines specialist proposals.
        builder.add_edge("art_director_review", "curator")

        # 5) EXECUTION — compile, generate/archive, then write the user-facing reply.
        builder.add_edge("curator", "prompt_compiler")
        builder.add_edge("prompt_compiler", "image_worker")
        builder.add_edge("image_worker", "assistant_agent")
        builder.add_edge("assistant_agent", END)
        self.compiled = builder.compile(checkpointer=checkpointer)
