from langgraph.types import Send

from app.agents.common import AGENTS, latest_by_agent


MAX_ATTEMPTS = 3


def route_review(state: dict) -> str | list[Send]:
    latest_reviews = latest_by_agent(state.get("reviews", []))
    attempts = state.get("attempts", {})
    retry_agents = [
        agent
        for agent in AGENTS
        if (
            agent not in latest_reviews
            or not latest_reviews[agent].get("approved", False)
        )
        and int(attempts.get(agent, 0)) < MAX_ATTEMPTS
    ]
    if retry_agents:
        return [Send(f"{agent}_agent", state) for agent in retry_agents]
    return "curator"
