"""Semantic loop circuit breaker for LangGraph execution."""

from __future__ import annotations

import hashlib
import json


class LoopCircuitOpen(RuntimeError):
    """Raised when a node repeats without producing observable progress."""


class LoopGuard:
    def __init__(self, max_same_signature: int = 3, max_node_visits: int = 4) -> None:
        self.max_same_signature = max(2, max_same_signature)
        self.max_node_visits = max(2, max_node_visits)
        self._signatures: dict[tuple[str, str], int] = {}
        self._visits: dict[str, int] = {}

    def observe(self, node: str, update: dict) -> None:
        self._visits[node] = self._visits.get(node, 0) + 1
        if self._visits[node] > self.max_node_visits:
            raise LoopCircuitOpen(f"循环熔断：{node} 超过 {self.max_node_visits} 次执行上限")
        stable = {
            key: value
            for key, value in update.items()
            if key not in {"events", "attempts"}
        }
        digest = hashlib.sha256(
            json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        key = (node, digest)
        self._signatures[key] = self._signatures.get(key, 0) + 1
        if self._signatures[key] >= self.max_same_signature:
            raise LoopCircuitOpen(
                f"循环熔断：{node} 连续 {self.max_same_signature} 次没有产生新状态"
            )
