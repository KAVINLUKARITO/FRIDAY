"""DeepSeekResponse model and response validator.

Validation rules:
- Must be valid JSON (no markdown fences)
- Must contain keys: analysis, diff, risk_score
- diff must not be empty
- risk_score must be float in [0.0, 1.0]

Empty or None input must not crash — returns invalid DeepSeekResponse.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class DeepSeekResponse:
    """Structured response from DeepSeek code generation.

    Attributes:
        valid: Whether the response passed all validation checks.
        analysis: Model's analysis of the change request.
        diff: Unified diff string of proposed changes.
        risk_score: Float in [0.0, 1.0] — model's risk assessment.
        errors: List of validation error messages (empty if valid).
    """
    valid: bool
    analysis: str = ""
    diff: str = ""
    risk_score: float = 0.0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "analysis": self.analysis,
            "diff": self.diff,
            "risk_score": self.risk_score,
            "errors": list(self.errors),
        }


_REQUIRED_KEYS = frozenset({"analysis", "diff", "risk_score"})


def _validate_response(raw: str) -> DeepSeekResponse:
    """Parse and validate a raw LLM response string.

    Args:
        raw: Raw string output from the LLM backend.

    Returns:
        A :class:`DeepSeekResponse`. Never raises.
    """
    errors: List[str] = []

    # Guard: empty or non-string input
    if not raw or not isinstance(raw, str):
        return DeepSeekResponse(
            valid=False, analysis="", diff="", risk_score=0.0,
            errors=["Empty or non-string input"],
        )

    # Strip markdown code fences if present
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Remove first and last fence lines
        inner = [l for l in lines if not l.strip().startswith("```")]
        stripped = "\n".join(inner).strip()

    # Parse JSON
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError) as exc:
        return DeepSeekResponse(
            valid=False, analysis="", diff="", risk_score=0.0,
            errors=[f"Invalid JSON: {exc}"],
        )

    if not isinstance(data, dict):
        return DeepSeekResponse(
            valid=False, analysis="", diff="", risk_score=0.0,
            errors=["Response must be a JSON object"],
        )

    # Check required keys
    missing = _REQUIRED_KEYS - set(data.keys())
    if missing:
        errors.append(f"Missing required keys: {sorted(missing)}")

    analysis = str(data.get("analysis", ""))
    diff = str(data.get("diff", ""))
    raw_risk = data.get("risk_score", None)

    # Validate diff
    if not diff or not diff.strip():
        errors.append("diff must not be empty")

    # Validate risk_score
    risk_score = 0.0
    if raw_risk is None:
        errors.append("risk_score is missing")
    else:
        try:
            risk_score = float(raw_risk)
        except (TypeError, ValueError):
            errors.append(f"risk_score must be a float, got: {type(raw_risk).__name__}")
            risk_score = 0.0
        else:
            if not (0.0 <= risk_score <= 1.0):
                errors.append(f"risk_score must be in [0, 1], got: {risk_score}")

    if errors:
        return DeepSeekResponse(
            valid=False,
            analysis=analysis,
            diff=diff,
            risk_score=risk_score,
            errors=errors,
        )

    return DeepSeekResponse(
        valid=True,
        analysis=analysis,
        diff=diff,
        risk_score=risk_score,
        errors=[],
    )
