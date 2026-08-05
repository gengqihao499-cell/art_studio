def merge_attempts(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    merged = dict(left or {})
    for agent, attempt in (right or {}).items():
        merged[agent] = max(merged.get(agent, 0), attempt)
    return merged

