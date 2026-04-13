"""Coder adapter that returns validated unified diffs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional, Protocol

from aiworker.llm.planner_adapter import TaskSpec


class GenerationBackend(Protocol):
    """Minimal backend protocol."""

    def generate(self, prompt: str) -> str:
        """Return raw model output."""


class PatchGenerator(Protocol):
    """Patch generator protocol for orchestrated loop injection."""

    def generate(self, task: TaskSpec, goal: str) -> Optional[str]:
        """Return unified diff string or ``None`` on generation failure."""


@dataclass(frozen=True)
class CoderPayload:
    analysis: str
    diff: str
    risk_score: float


def _ensure_json_only(raw: str) -> dict[str, object]:
    text = raw.strip()
    if not text:
        raise ValueError("Coder returned empty response")
    if "```" in text:
        raise ValueError("Coder response contains markdown")
    if not (text.startswith("{") and text.endswith("}")):
        raise ValueError("Coder response must be JSON object only")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Coder response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Coder response root must be object")
    return parsed


def _validate_payload(payload: dict[str, object]) -> CoderPayload:
    analysis = payload.get("analysis")
    diff = payload.get("diff")
    risk_score = payload.get("risk_score")

    if not isinstance(analysis, str) or not analysis.strip():
        raise ValueError("analysis must be non-empty string")
    if not isinstance(diff, str) or "diff --git" not in diff:
        raise ValueError("diff must be unified diff containing 'diff --git'")
    if not isinstance(risk_score, (int, float)):
        raise ValueError("risk_score must be numeric")
    risk = float(risk_score)
    if risk < 0.0 or risk > 1.0:
        raise ValueError("risk_score must be in [0,1]")

    return CoderPayload(analysis=analysis.strip(), diff=diff, risk_score=risk)


class CoderAdapter(PatchGenerator):
    """Coder model adapter with strict JSON validation."""

    def __init__(self, backend: GenerationBackend) -> None:
        self._backend = backend
        self._last_risk_score: float = 0.0

    @property
    def last_risk_score(self) -> float:
        """Risk score from last successful payload parse."""
        return self._last_risk_score

    def _build_prompt(self, task: TaskSpec, goal: str) -> str:
        return (
            "You are a coding model.\n"
            "Return JSON ONLY. No markdown. No prose.\n\n"
            "GOAL:\n"
            f"{goal}\n\n"
            "TASK:\n"
            f"{task.type}: {task.description}\n\n"
            "FILE:\n"
            f"{task.file}\n\n"
            "MAX_LINES:\n"
            f"{task.max_lines}\n\n"
            "SAFETY RULES:\n"
            "- One file only\n"
            "- No path traversal\n"
            "- Keep changes within max_lines\n"
            "- Return unified diff only in diff field\n\n"
            "RESPONSE JSON SCHEMA:\n"
            '{"analysis":"...","diff":"diff --git a/... b/...","risk_score":0.1}'
        )

    def generate(self, task: TaskSpec, goal: str) -> Optional[str]:
        raw = self._backend.generate(self._build_prompt(task, goal))
        payload = _ensure_json_only(raw)
        parsed = _validate_payload(payload)
        self._last_risk_score = parsed.risk_score
        return parsed.diff


__all__ = ["CoderAdapter", "CoderPayload", "GenerationBackend", "PatchGenerator"]
