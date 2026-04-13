"""DeepSeek adapter compatibility layer.

Exports the strict-JSON repair helpers expected by the reasoning tests and
the unified-diff patch generator expected by the autonomy tests.
"""

from __future__ import annotations

import json
import subprocess
import re
import os
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

from aiworker.monitor.telemetry import telemetry
from aiworker.llm.ollama_backend import _safe_env
from aiworker.llm.prompt_builder import build_generation_prompt
from aiworker.llm.response import DeepSeekResponse

if TYPE_CHECKING:
    from aiworker.planning.models import Plan
    from aiworker.reasoning.planner import ReasoningPlan


def _strip_code_fences(raw: str) -> str:
    stripped = raw.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _validate_response(raw: str | None) -> DeepSeekResponse:
    """Parse and validate a strict JSON response."""
    if not raw or not isinstance(raw, str):
        return DeepSeekResponse(
            valid=False,
            errors=["Empty response from backend"],
        )

    stripped = _strip_code_fences(raw)

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return DeepSeekResponse(
            valid=False,
            errors=[f"Response is not valid JSON: {exc}"],
        )

    if not isinstance(payload, dict):
        return DeepSeekResponse(
            valid=False,
            errors=["Response is not a JSON object"],
        )

    errors: list[str] = []
    required_keys = {"analysis", "diff", "risk_score"}
    missing = required_keys - set(payload)
    if missing:
        errors.append(f"Missing required keys: {sorted(missing)}")

    analysis = str(payload.get("analysis", ""))
    diff = str(payload.get("diff", ""))
    raw_risk = payload.get("risk_score")

    try:
        risk_score = float(raw_risk)
    except (TypeError, ValueError):
        risk_score = 0.0
        errors.append(f"risk_score is not a number: {raw_risk!r}")
    else:
        if not 0.0 <= risk_score <= 1.0:
            errors.append(f"risk_score must be in [0, 1], got {risk_score}")

    if not diff.strip():
        errors.append("diff field is empty")

    return DeepSeekResponse(
        valid=not errors,
        analysis=analysis,
        diff=diff,
        risk_score=risk_score,
        errors=errors,
    )


def _invalid_response() -> DeepSeekResponse:
    return DeepSeekResponse(
        valid=False,
        analysis="",
        diff="",
        risk_score=1.0,
        errors=["invalid_json"],
    )


def _build_prompt(plan: ReasoningPlan) -> str:
    """Build the strict JSON repair prompt from a ReasoningPlan."""
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
    """Prompt-in, string-out backend interface."""

    def generate(self, prompt: str) -> str:
        ...


class StubBackend:
    """Deterministic backend used by tests."""

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
    """Adapter that enforces strict JSON responses from a backend."""

    def __init__(self, backend: GenerationBackend, max_retries: int = 2) -> None:
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
            errors=["No response generated"],
        )

    @property
    def total_calls(self) -> int:
        return self._total_calls


def _build_patch_prompt(
    goal: str,
    allowed_files: tuple[str, ...],
    plan_steps: str,
    temperature: float,
    seed: Optional[int],
) -> str:
    """Build a deterministic patch-generation prompt."""
    files_str = ", ".join(allowed_files) if allowed_files else "(any)"
    parts = [
        "You are a precise code generation tool.",
        f"Use temperature {temperature} and be deterministic.",
    ]
    if seed is not None:
        parts.append(f"Use seed {seed} for reproducibility.")
    parts.extend(
        [
            "",
            "GOAL:",
            goal,
            "",
            "ALLOWED FILES:",
            files_str,
            "",
            "PLAN:",
            plan_steps,
            "",
            "INSTRUCTIONS:",
            "Return ONLY a valid unified diff patch.",
            "No markdown.",
            "No explanations.",
            "No backticks.",
            "The output must start with 'diff --git' on the very first line.",
            "Do not include any text before or after the diff.",
        ]
    )
    return "\n".join(parts)


def _format_plan_steps(plan: Plan) -> str:
    """Format plan steps into a stable, readable prompt section."""
    steps = getattr(plan, "steps", ()) or ()
    if not steps:
        complexity = getattr(plan, "complexity_score", 0.0)
        return f"Implement: {getattr(plan, 'goal', '')} (complexity: {complexity:.1f})"

    lines: list[str] = []
    for index, step in enumerate(steps, start=1):
        step_id = getattr(step, "step_id", index)
        description = getattr(step, "description", str(step))
        risk = getattr(step, "estimated_risk", "unknown")
        lines.append(f"  {step_id}. {description} [risk={risk}]")
    return "\n".join(lines)


def _validate_diff_output(raw: str | None) -> Optional[str]:
    """Return a cleaned unified diff or ``None``."""
    if not raw or not isinstance(raw, str):
        return None

    cleaned = raw.strip()
    if "```" in cleaned:
        return None
    if not cleaned.startswith("diff --git"):
        return None
    return cleaned


class DeepSeekAdapter:
    """Compatibility adapter for both strict JSON and patch generation flows."""

    def __init__(
        self,
        backend: Optional[GenerationBackend] = None,
        model_name: str = "deepseek-coder:7b",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        if not model_name or not model_name.strip():
            raise ValueError("model_name must be a non-empty string")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")

        default_temperature = 0.0 if backend is not None else 0.2
        default_max_tokens = 4096 if backend is not None else 2048
        default_timeout = 120 if backend is not None else 180

        resolved_temperature = default_temperature if temperature is None else temperature
        resolved_max_tokens = default_max_tokens if max_tokens is None else max_tokens
        resolved_timeout = default_timeout if timeout is None else timeout

        if not 0.0 <= resolved_temperature <= 2.0:
            raise ValueError(
                f"temperature must be in [0.0, 2.0], got {resolved_temperature}"
            )
        if resolved_max_tokens < 1:
            raise ValueError(f"max_tokens must be >= 1, got {resolved_max_tokens}")
        if resolved_timeout < 1:
            raise ValueError(f"timeout must be >= 1, got {resolved_timeout}")

        self._backend = backend
        self._model_name = model_name.strip()
        self._temperature = float(resolved_temperature)
        self._max_tokens = int(resolved_max_tokens)
        self._timeout = int(resolved_timeout)
        self._max_retries = max_retries
        self.total_calls = 0

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def temperature(self) -> float:
        return self._temperature

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def timeout(self) -> int:
        return self._timeout

    @property
    def max_retries(self) -> int:
        return self._max_retries

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": "deepseek",
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }

    def generate(
        self,
        plan,
        goal: Optional[str] = None,
        allowed_files: Optional[tuple[str, ...] | list[str]] = None,
        seed: Optional[int] = None,
    ) -> Optional[DeepSeekResponse | str]:
        if plan is None:
            return None
        if self._backend is not None:
            return self._generate_json(plan, goal=goal, allowed_files=allowed_files)
        return self._generate_diff(plan, goal=goal, allowed_files=allowed_files, seed=seed)

    def _generate_json(
        self,
        plan,
        goal: Optional[str],
        allowed_files: Optional[tuple[str, ...] | list[str]],
    ) -> Optional[DeepSeekResponse]:
        goal_text = goal or getattr(plan, "goal", None) or str(plan)
        steps = getattr(plan, "steps", ()) or ()
        if isinstance(plan, str):
            plan_summary = plan
        elif steps:
            plan_summary = "\n".join(
                getattr(step, "description", str(step))
                for step in steps
            )
        else:
            plan_summary = goal_text

        prompt = build_generation_prompt(
            goal=goal_text,
            plan_summary=plan_summary,
            allowed_files=list(allowed_files or ()),
        )

        attempts = max(1, self._max_retries)
        last_response: Optional[DeepSeekResponse] = None
        structured_fallback = self._should_return_invalid_response(plan)
        for _ in range(attempts):
            self.total_calls += 1
            try:
                raw = self._backend.generate(prompt)
            except Exception:
                telemetry.record_error("RepairAdapter backend generation failed")
                last_response = _invalid_response()
                continue
            telemetry.record_llm_call(
                prompt_tokens=max(1, len(prompt) // 4),
                completion_tokens=max(1, len(raw) // 4),
                confidence=max(0.0, 1.0 - getattr(plan, "risk_score", 0.0)),
                model=self._model_name,
            )
            response = _validate_response(raw)
            last_response = response
            if response.valid:
                return response
            last_response = _invalid_response()
        if structured_fallback:
            return last_response or _invalid_response()
        return None

    @staticmethod
    def _should_return_invalid_response(plan: object) -> bool:
        return any(
            hasattr(plan, attribute)
            for attribute in (
                "hypothesis",
                "strategy",
                "failure_type",
                "affected_modules",
                "failing_tests",
            )
        )

    import re

    def extract_unified_diff(text: str) -> str | None:
      pattern = r"--- .?\n\+\+\+ .?\n@@[\s\S]*"
      match = re.search(pattern, text)
      if match:
         return match.group(0)
      return None

    def _generate_diff(
        self,
        plan: Plan,
        goal: Optional[str],
        allowed_files: Optional[tuple[str, ...] | list[str]],
        seed: Optional[int],
    ) -> Optional[str]:
        goal_text = goal or getattr(plan, "goal", "")
        files = tuple(allowed_files or ("*.py",))
        prompt = _build_patch_prompt(
            goal=goal_text,
            allowed_files=files,
            plan_steps=_format_plan_steps(plan),
            temperature=self._temperature,
            seed=seed,
        )

        try:
            result = subprocess.run(
                ["ollama", "run", self._model_name],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=_safe_env(),
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            telemetry.record_error("DeepSeekAdapter diff generation failed")
            return None

        if result.returncode != 0:
            telemetry.record_error("DeepSeekAdapter diff generation returned non-zero exit code")
            return None
        telemetry.record_llm_call(
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=max(1, len(result.stdout) // 4),
            model=self._model_name,
        )
        return _validate_diff_output(result.stdout)
