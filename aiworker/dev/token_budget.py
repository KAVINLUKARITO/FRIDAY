"""Deterministic token budget enforcement for generation requests."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TokenBudgetResult:
    allowed: bool
    prompt_tokens: int
    expected_diff_tokens: int
    total_tokens: int
    hard_cap: int
    error: str | None


def estimate_tokens(text: str) -> int:
    """Estimate tokens deterministically using character length heuristic."""
    if not text:
        return 0
    return int(math.ceil(len(text) / 4.0))


def estimate_diff_tokens(expected_diff_lines: int) -> int:
    """Estimate tokens for expected unified diff output."""
    bounded_lines = max(0, expected_diff_lines)
    return bounded_lines * 6


def enforce_token_budget(
    *,
    prompt: str,
    expected_diff_lines: int,
    hard_cap: int,
) -> TokenBudgetResult:
    """Return deterministic budget decision for generation request."""
    prompt_tokens = estimate_tokens(prompt)
    diff_tokens = estimate_diff_tokens(expected_diff_lines)
    total = prompt_tokens + diff_tokens

    if total > hard_cap:
        return TokenBudgetResult(
            allowed=False,
            prompt_tokens=prompt_tokens,
            expected_diff_tokens=diff_tokens,
            total_tokens=total,
            hard_cap=hard_cap,
            error="Token budget exceeded",
        )

    return TokenBudgetResult(
        allowed=True,
        prompt_tokens=prompt_tokens,
        expected_diff_tokens=diff_tokens,
        total_tokens=total,
        hard_cap=hard_cap,
        error=None,
    )


__all__ = [
    "TokenBudgetResult",
    "enforce_token_budget",
    "estimate_diff_tokens",
    "estimate_tokens",
]
