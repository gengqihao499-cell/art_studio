"""Layers 2 and 3: deterministic snip plus turn-based time decay."""

from __future__ import annotations

import math
import re

from app.context.artifact_offloader import ArtifactOffloader


def _terms(text: str) -> set[str]:
    latin = re.findall(r"[a-zA-Z0-9_]{2,}", text.lower())
    chinese = [text[index : index + 2] for index in range(max(0, len(text) - 1))]
    return set(latin + chinese)


class MicroCompactor:
    def __init__(
        self,
        offloader: ArtifactOffloader,
        full_turns: int = 2,
        micro_turns: int = 8,
        half_life_turns: float = 6.0,
    ) -> None:
        self.offloader = offloader
        self.full_turns = max(1, full_turns)
        self.micro_turns = max(self.full_turns + 1, micro_turns)
        self.half_life_turns = max(1.0, half_life_turns)

    def compact(
        self,
        messages: list[dict],
        *,
        current_sequence: int,
        current_request: str,
        locked_constraints: list[str],
        project_id: str,
        session_id: str,
        run_id: str | None,
    ) -> tuple[list[dict], dict]:
        query_terms = _terms(current_request)
        locked_text = " ".join(str(item) for item in locked_constraints)
        projected: list[dict] = []
        counts = {"full": 0, "micro": 0, "snipped": 0, "dropped": 0}
        for row in messages:
            message = dict(row)
            content = str(message.get("content") or "")
            sequence = int(message.get("turn_sequence") or current_sequence)
            age = max(0, current_sequence - sequence)
            pinned = bool(locked_text and any(part in content for part in locked_constraints if part))
            overlap = len(query_terms & _terms(content)) / max(1, len(query_terms))
            decay = math.exp(-math.log(2) * age / self.half_life_turns)
            score = min(1.0, 0.55 * overlap + 0.25 * decay + (0.20 if pinned else 0.0))
            base = {
                "id": message.get("id"),
                "role": message.get("role"),
                "turn_id": message.get("turn_id"),
                "turn_sequence": sequence,
                "age_turns": age,
                "relevance": round(score, 4),
            }
            artifact = self.offloader.offload_text(
                content,
                project_id=project_id,
                session_id=session_id,
                run_id=run_id,
                artifact_type="conversation_message",
            )
            if age <= self.full_turns:
                projected.append({**base, "content": content, "mode": "full", "artifact": artifact})
                counts["full"] += 1
            elif age <= self.micro_turns or pinned or score >= 0.38:
                preview = content if len(content) <= 520 else content[:520] + "…"
                projected.append({**base, "content": preview, "mode": "micro", "artifact": artifact})
                counts["micro"] += 1
            elif artifact:
                projected.append({**base, "content": artifact["preview"], "mode": "snip", "artifact": artifact})
                counts["snipped"] += 1
            else:
                counts["dropped"] += 1
        return projected, counts
