"""# FILE: aiworker/llm/repair_adapter.py — Strict JSON repair adapter for reasoning plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

from aiworker.reasoning.planner import ReasoningPlan

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class DeepSeekResponse:
    """Validated repair response from an LLM backend."""

    valid: bool
    analysis: str = ""
    diff: str = ""
    risk_score: float = 0.0
    raw_output: str = ""
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "analysis": self.analysis,
            "diff": self.diff,
            "risk_score": self.risk_score,
            "errors": list(self.errors),
        }


_REQUIRED_KEYS = frozenset({"analysis", "diff", "risk_score"})


def _validate_response(raw: str) -> DeepSeekResponse:
    """Validate raw backend output as a strict JSON object."""
    if not raw or not raw.strip():
        return DeepSeekResponse(
            valid=False,
            raw_output=raw,
            errors=("Empty response from backend",),
        )

    try:
        payload = json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        return DeepSeekResponse(
            valid=False,
            raw_output=raw,
            errors=(f"Response is not valid JSON: {exc}",),
        )

    if not isinstance(payload, dict):
        return DeepSeekResponse(
            valid=False,
            raw_output=raw,
            errors=("Response is not a JSON object",),
        )

    errors: list[str] = []
    missing = _REQUIRED_KEYS - set(payload)
    if missing:
        errors.append(f"Missing required keys: {sorted(missing)}")

    analysis = str(payload.get("analysis", ""))
    diff = str(payload.get("diff", ""))
    risk_raw = payload.get("risk_score", -1)
    try:
        risk_score = float(risk_raw)
    except (TypeError, ValueError):
        risk_score = -1.0
        errors.append(f"risk_score is not a number: {risk_raw!r}")

    if risk_score != -1.0 and not 0.0 <= risk_score <= 1.0:
        errors.append(f"risk_score must be in [0, 1], got {risk_score}")

    if not diff.strip():
        errors.append("diff field is empty")

    return DeepSeekResponse(
        valid=not errors,
        analysis=analysis,
        diff=diff,
        risk_score=max(0.0, min(1.0, risk_score)) if risk_score >= 0 else 0.0,
        raw_output=raw,
        errors=tuple(errors),
    )


def _build_prompt(plan: ReasoningPlan) -> str:
    """Build a strict JSON repair prompt."""
    parts = [
        "You are a code repair assistant.",
        "Respond with ONLY a JSON object. No markdown or commentary.",
        'Schema: {"analysis": "<string>", "diff": "<unified diff>", "risk_score": <float 0-1>}',
        "",
        f"Failure type: {plan.failure_type}",
        f"Hypothesis: {plan.hypothesis}",
        f"Strategy: {plan.strategy}",
        f"Risk estimate: {plan.risk_score}",
    ]

    if plan.affected_modules:
        parts.append(f"Affected modules: {', '.join(plan.affected_modules)}")
    if plan.failing_tests:
        parts.append(f"Failing tests: {', '.join(plan.failing_tests)}")
    if plan.context and plan.context.files:
        parts.append("")
        parts.append("Relevant files:")
        for file_context in plan.context.files[:5]:
            parts.append(f"--- {file_context.file_path} ---")
            parts.append(file_context.content[:2000])

    return "\n".join(parts)


@runtime_checkable
class GenerationBackend(Protocol):
    """Protocol for prompt-in, string-out repair backends."""

    def generate(self, prompt: str) -> str:
        ...


class StubBackend:
    """Deterministic backend for tests."""

    def __init__(self, response: str) -> None:
        self._response = response
        self._call_count = 0
        self._last_prompt = ""

    def generate(self, prompt: str) -> str:
        self._call_count += 1
        self._last_prompt = prompt
        return self._response

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def last_prompt(self) -> str:
        return self._last_prompt


class RepairAdapter:
    """Repair-plan adapter that enforces strict JSON responses."""

    def __init__(
        self,
        backend: GenerationBackend,
        max_retries: int = 2,
    ) -> None:
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        self.backend = backend
        self.max_retries = max_retries
        self._total_calls = 0

    def generate(self, plan: ReasoningPlan) -> DeepSeekResponse:
        prompt = _build_prompt(plan)
        last_response: Optional[DeepSeekResponse] = None
        for _ in range(self.max_retries):
            self._total_calls += 1
            response = _validate_response(self.backend.generate(prompt))
            last_response = response
            if response.valid:
                return response
        return last_response or DeepSeekResponse(
            valid=False,
            errors=("No response generated",),
        )

    @property
    def total_calls(self) -> int:
        return self._total_calls
