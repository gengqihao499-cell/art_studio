"""Token budgeting helpers.

ArtFlow intentionally uses a deterministic estimate instead of a tokenizer
dependency. Provider-reported usage remains available in Agent logs.
"""

from __future__ import annotations

import json


def estimate_tokens(value: object) -> int:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    # Chinese text is often closer to one token per character, while latin text
    # is cheaper. 0.55 is a conservative mixed-language estimate.
    return max(1, int(len(text) * 0.55))


class ContextBudgetManager:
    def __init__(self, max_tokens: int, auto_compact_ratio: float = 0.75) -> None:
        self.max_tokens = max(1000, max_tokens)
        self.auto_compact_ratio = min(0.95, max(0.5, auto_compact_ratio))

    def usage(self, value: object) -> dict:
        tokens = estimate_tokens(value)
        return {
            "estimated_tokens": tokens,
            "max_tokens": self.max_tokens,
            "usage_ratio": round(tokens / self.max_tokens, 4),
        }

    def should_auto_compact(self, raw_token_total: int, sequence: int) -> bool:
        # The periodic trigger avoids accumulating stale decisions even when
        # individual messages are short.
        return raw_token_total >= int(self.max_tokens * self.auto_compact_ratio) or (
            sequence > 0 and sequence % 10 == 0
        )
