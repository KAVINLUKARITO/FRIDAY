"""Confidence scoring engine for architecture patch acceptance."""

from __future__ import annotations

from aiworker.orchestration.architecture_models import SandboxResult


def _clamp_01(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_confidence(
    tests_passed_ratio: float,
    no_import_errors: bool,
    no_runtime_exceptions: bool,
    risk_score: float,
) -> float:
    """Compute bounded confidence score from deterministic metrics."""
    tests_component = _clamp_01(tests_passed_ratio)
    import_component = 1.0 if no_import_errors else 0.0
    runtime_component = 1.0 if no_runtime_exceptions else 0.0
    risk_component = 1.0 - _clamp_01(risk_score)

    confidence = (
        0.4 * tests_component
        + 0.3 * import_component
        + 0.2 * runtime_component
        + 0.1 * risk_component
    )
    return _clamp_01(confidence)


def compute_confidence_from_sandbox(sandbox_result: SandboxResult, risk_score: float) -> float:
    """Compute confidence from sandbox result and model-reported risk score."""
    total = sandbox_result.tests_total
    ratio = 1.0 if total <= 0 else sandbox_result.tests_passed / total

    return compute_confidence(
        tests_passed_ratio=ratio,
        no_import_errors=sandbox_result.import_errors == 0,
        no_runtime_exceptions=sandbox_result.runtime_exceptions == 0,
        risk_score=risk_score,
    )
