"""Strict schema enforcement for generated patch payloads."""

from __future__ import annotations

import json
from typing import Any

from aiworker.orchestration.architecture_models import (
    ValidatedPatch,
    ValidationResult,
)


_REQUIRED_KEYS = {"analysis", "diff", "risk_score"}


def _invalid(message: str) -> ValidationResult:
    return ValidationResult(is_valid=False, error=message, patch=None)


def _is_markdown_wrapped(payload: str) -> bool:
    return "```" in payload


def validate_patch_payload(payload: str) -> ValidationResult:
    """Validate strict JSON schema for generated patch payloads."""
    trimmed = payload.strip()
    if not trimmed:
        return _invalid("Payload is empty")
    if _is_markdown_wrapped(trimmed):
        return _invalid("Markdown wrappers are not allowed")
    if not (trimmed.startswith("{") and trimmed.endswith("}")):
        return _invalid("Payload must be a single JSON object")

    try:
        raw: Any = json.loads(trimmed)
    except json.JSONDecodeError:
        return _invalid("Payload is not valid JSON")

    if not isinstance(raw, dict):
        return _invalid("Payload root must be a JSON object")

    keys = set(raw.keys())
    if keys != _REQUIRED_KEYS:
        return _invalid("Payload keys must exactly match analysis, diff, risk_score")

    analysis = raw["analysis"]
    diff = raw["diff"]
    risk_score = raw["risk_score"]

    if not isinstance(analysis, str):
        return _invalid("analysis must be a string")
    if not isinstance(diff, str):
        return _invalid("diff must be a string")
    if not diff.strip():
        return _invalid("diff must not be empty")
    if isinstance(risk_score, bool) or not isinstance(risk_score, (int, float)):
        return _invalid("risk_score must be a float in range [0, 1]")

    risk_value = float(risk_score)
    if risk_value < 0.0 or risk_value > 1.0:
        return _invalid("risk_score must be within [0, 1]")

    patch = ValidatedPatch(analysis=analysis, diff=diff, risk_score=risk_value)
    return ValidationResult(is_valid=True, error=None, patch=patch)
