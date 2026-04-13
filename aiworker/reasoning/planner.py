"""Reasoning planner for the autonomous repair pipeline.

When root cause analysis cannot resolve a failure deterministically,
the planner builds a structured :class:`ReasoningPlan` that guides
the LLM adapter to generate a targeted patch.

Uses the module mapper and context assembler to scope the plan to
only the affected parts of the codebase.

No network calls, no randomness, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from aiworker.debugger.capture import FailureReport
from aiworker.debugger.root_cause import RootCauseResult
from aiworker.reasoning.module_mapper import (
    ModuleNode,
    affected_module_paths,
    map_dependencies,
)
from aiworker.reasoning.context_assembler import (
    AssembledContext,
    assemble_context,
)


@dataclass(frozen=True)
class ReasoningPlan:
    """Structured repair plan for the LLM adapter.

    Attributes:
        hypothesis: What we think is wrong and why.
        affected_modules: Dotted module paths that may need changes.
        risk_score: Estimated risk of the repair [0, 1].
        strategy: High-level approach description.
        context: Assembled source context for the LLM (optional).
        failure_type: The exception type that triggered this plan.
        failing_tests: Tests that need to pass after repair.
    """

    hypothesis: str
    affected_modules: tuple[str, ...]
    risk_score: float
    strategy: str
    context: Optional[AssembledContext] = None
    failure_type: str = ""
    failing_tests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.hypothesis or not self.hypothesis.strip():
            errors.append("hypothesis must be a non-empty string")
        if not (0.0 <= self.risk_score <= 1.0):
            errors.append(
                f"risk_score must be in [0, 1], got {self.risk_score}"
            )
        if not self.strategy or not self.strategy.strip():
            errors.append("strategy must be a non-empty string")
        if errors:
            raise ValueError(
                "Invalid ReasoningPlan: " + "; ".join(errors)
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "hypothesis": self.hypothesis,
            "affected_modules": list(self.affected_modules),
            "risk_score": self.risk_score,
            "strategy": self.strategy,
            "context": self.context.to_dict() if self.context else None,
            "failure_type": self.failure_type,
            "failing_tests": list(self.failing_tests),
        }


def _compute_risk_score(
    report: FailureReport,
    root_cause: RootCauseResult,
    module_count: int,
) -> float:
    """Compute a risk score for the repair plan.

    Higher risk means more caution is needed.  Deterministic formula:
    - Base risk from category: structural=0.3, state=0.4, behavioral=0.5, unknown=0.6
    - +0.05 per affected file (capped at +0.2)
    - +0.1 if root cause is unresolved
    - Clamp to [0, 1]
    """
    category_base = {
        "structural": 0.3,
        "state": 0.4,
        "behavioral": 0.5,
        "unknown": 0.6,
    }
    base = category_base.get(root_cause.category, 0.6)
    file_risk = min(0.05 * len(report.affected_files), 0.2)
    unresolved_risk = 0.1 if not root_cause.resolved else 0.0

    return round(min(1.0, max(0.0, base + file_risk + unresolved_risk)), 3)


def _build_hypothesis(
    report: FailureReport,
    root_cause: RootCauseResult,
) -> str:
    """Build a hypothesis string from failure context."""
    parts: list[str] = []

    parts.append(
        f"Exception '{report.exception_type}' occurred: {report.message}"
    )

    if root_cause.explanation:
        parts.append(f"Analysis: {root_cause.explanation}")

    if report.affected_files:
        files_str = ", ".join(report.affected_files[:5])
        parts.append(f"Affected files: {files_str}")

    return "  ".join(parts)


def _build_strategy(
    report: FailureReport,
    root_cause: RootCauseResult,
) -> str:
    """Build a strategy string for the repair."""
    if root_cause.suggested_fix:
        return f"Apply deterministic fix: {root_cause.suggested_fix}"

    strategies: list[str] = []

    if report.failing_tests:
        strategies.append(
            f"Fix the {len(report.failing_tests)} failing test(s)"
        )

    if report.affected_files:
        strategies.append(
            f"Examine and repair {len(report.affected_files)} affected file(s)"
        )

    strategies.append(
        "Generate a minimal unified diff that resolves the error "
        "without introducing new failures"
    )

    return "; ".join(strategies)


def create_plan(
    report: FailureReport,
    root_cause: RootCauseResult,
    repo_root: str = "",
    max_depth: int = 2,
) -> ReasoningPlan:
    """Build a structured repair plan from failure context.

    If ``repo_root`` is provided, the planner uses the module mapper
    to discover dependencies and the context assembler to extract
    relevant source code.

    Args:
        report: The captured failure information.
        root_cause: Result from root cause analysis.
        repo_root: Path to the repository root (optional).
        max_depth: Dependency traversal depth.

    Returns:
        A frozen :class:`ReasoningPlan`.
    """
    # Identify affected modules
    if repo_root and report.affected_files:
        affected = affected_module_paths(report.affected_files, repo_root)
    else:
        affected = ()

    # Map dependencies if repo root is available
    context: Optional[AssembledContext] = None
    nodes: tuple[ModuleNode, ...] = ()
    if repo_root and affected:
        try:
            nodes = map_dependencies(
                root_modules=affected,
                repo_root=repo_root,
                max_depth=max_depth,
            )
            context = assemble_context(nodes, repo_root)
        except Exception:
            pass

    risk = _compute_risk_score(report, root_cause, len(affected))
    hypothesis = _build_hypothesis(report, root_cause)
    strategy = _build_strategy(report, root_cause)

    return ReasoningPlan(
        hypothesis=hypothesis,
        affected_modules=affected,
        risk_score=risk,
        strategy=strategy,
        context=context,
        failure_type=report.exception_type,
        failing_tests=report.failing_tests,
    )
