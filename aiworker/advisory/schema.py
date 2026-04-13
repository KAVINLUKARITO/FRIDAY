"""Data models for the LLM advisory layer.

Provides an immutable dataclass for advisory results.
No execution logic, no database access, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AdvisoryResult:
    """Structured result returned by the LLM advisory layer.

    Attributes:
        suggested_improvements: List of actionable improvement suggestions.
        risk_analysis: Human-readable risk assessment.
        alternative_strategy: Description of an alternative approach.
        advisory_confidence: Confidence in the advisory ``[0, 1]``.
    """

    suggested_improvements: tuple[str, ...] = field(default_factory=tuple)
    risk_analysis: str = "LLM unavailable"
    alternative_strategy: str = ""
    advisory_confidence: float = 0.0
