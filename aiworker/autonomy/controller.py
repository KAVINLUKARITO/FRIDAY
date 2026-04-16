"""Autonomous evolution controller.

The :class:`EvolutionController` holds references to all subsystems
and exposes the :meth:`run` entry point that delegates to the
evolution loop.  It owns no mutable state beyond what the subsystems
themselves hold, and it never writes to the workspace directly.

The :class:`PatchGenerator` protocol defines the interface for
injectable patch generation strategies, enabling both LLM-backed
production use and deterministic stubs for testing.

The :class:`AutonomyController` is a thin scheduling/trigger layer
around :class:`EvolutionLoop` for future REST and scheduling
integration.

Design constraints:
- No global state.
- No hidden side effects.
- All subsystems injected via constructor.
"""

from __future__ import annotations

import subprocess
from typing import Optional, Protocol, runtime_checkable

from aiworker.autonomy.models import EvolutionConfig, EvolutionResult
from aiworker.governance.audit import AuditLog
from aiworker.governance.policy import PolicyEngine
from aiworker.memory.database import Database
from aiworker.planning.models import Plan


# -------------------------------------------------------------------
# Patch generator protocol
# -------------------------------------------------------------------

@runtime_checkable
class PatchGenerator(Protocol):
    """Protocol for generating unified diff patches from a plan.

    Implementations must be callable with a plan and optional seed,
    returning either a unified diff string or ``None`` on failure.
    """

    def generate(
        self,
        plan: Plan,
        goal: str,
        allowed_files: tuple[str, ...],
        seed: Optional[int] = None,
    ) -> Optional[str]:
        """Generate a unified diff patch from a plan.

        Args:
            plan: The structured plan to implement.
            goal: The evolution goal (for context).
            allowed_files: Files the patch may modify.
            seed: Optional deterministic seed for replay.

        Returns:
            A unified diff string, or ``None`` if generation failed.
        """
        ...


class StubPatchGenerator:
    """Deterministic patch generator for testing.

    Always returns the same patch regardless of input, unless
    ``fail_after`` is set, in which case it returns ``None`` after
    that many calls.

    Args:
        patch_text: The fixed patch to return.
        fail_after: Return ``None`` after this many successful calls.
            Set to 0 to always fail. ``None`` means never fail.
    """

    def __init__(
        self,
        patch_text: str,
        fail_after: Optional[int] = None,
    ) -> None:
        self._patch_text = patch_text
        self._fail_after = fail_after
        self._call_count = 0

    def generate(
        self,
        plan: Plan,
        goal: str,
        allowed_files: tuple[str, ...],
        seed: Optional[int] = None,
    ) -> Optional[str]:
        """Return the fixed patch, or ``None`` after fail_after calls."""
        self._call_count += 1
        if self._fail_after is not None and self._call_count > self._fail_after:
            return None
        return self._patch_text

    @property
    def call_count(self) -> int:
        """Number of times generate() has been called."""
        return self._call_count


# -------------------------------------------------------------------
# Git rollback helper (isolated function)
# -------------------------------------------------------------------

def git_rollback(workspace_path: str, target_ref: str = "HEAD") -> bool:
    """Attempt a ``git checkout`` rollback to *target_ref*.

    This is the **only** subprocess shell call in the autonomy module,
    isolated here for testability and auditability.

    Args:
        workspace_path: Absolute path to the git-controlled workspace.
        target_ref: Git ref to roll back to (default ``HEAD``).

    Returns:
        ``True`` if rollback succeeded, ``False`` otherwise.
    """
    try:
        result = subprocess.run(
            ["git", "checkout", target_ref, "--", "."],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


# -------------------------------------------------------------------
# Evolution controller
# -------------------------------------------------------------------

class EvolutionController:
    """Manages subsystem references and orchestrates the evolution loop.

    The controller itself is stateless — all mutable state lives in
    the injected subsystems (PolicyEngine, AuditLog, etc.).  Calling
    :meth:`run` delegates to :func:`aiworker.autonomy.loop.run_loop`.

    Args:
        config: Evolution parameters and safety bounds.
        policy_engine: Pre-configured governance gate.
        patch_generator: Callable that produces unified diffs from plans.
        workspace_path: Absolute path to the workspace directory
            (used only for sandbox copies — never directly modified).
        database: Optional database for memory persistence.
        audit_log: Shared audit log (if ``None``, a fresh one is
            created and attached to the policy engine).

    Raises:
        ValueError: If *workspace_path* is empty.
    """

    def __init__(
        self,
        config: EvolutionConfig,
        policy_engine: PolicyEngine,
        patch_generator: PatchGenerator,
        workspace_path: str,
        database: Optional[Database] = None,
        audit_log: Optional[AuditLog] = None,
    ) -> None:
        if not workspace_path or not workspace_path.strip():
            raise ValueError("workspace_path must be a non-empty string")

        self.config = config
        self.policy_engine = policy_engine
        self.patch_generator = patch_generator
        self.workspace_path = workspace_path
        self.database = database
        self.audit_log = audit_log or policy_engine.audit_log

    def run(self) -> EvolutionResult:
        """Execute the evolution loop and return an immutable result.

        Delegates to :func:`aiworker.autonomy.loop.run_loop`.

        Returns:
            An :class:`EvolutionResult` capturing everything that
            happened.
        """
        from aiworker.autonomy.run_loop import run_loop
        return run_loop(self)

    def summary(self, result: EvolutionResult) -> str:
        """Return a human-readable summary of an evolution result."""
        lines = [
            f"Evolution: {result.config.goal!r}",
            f"  Success: {result.success}",
            f"  Termination: {result.termination_reason}",
            f"  Attempts: {result.total_attempts} "
            f"({result.successful_attempts} succeeded, "
            f"{result.failed_attempts} failed)",
            f"  Final confidence: {result.final_confidence:.3f}",
        ]
        if result.detail:
            lines.append(f"  Detail: {result.detail}")
        return "\n".join(lines)


# -------------------------------------------------------------------
# Autonomy controller — thin orchestration layer
# -------------------------------------------------------------------


class AutonomyController:
    """High-level controller for autonomous evolution.

    Wraps an :class:`EvolutionLoop` and provides a single
    :meth:`evolve` entry point.  This layer exists for future
    scheduling, external triggers, and REST integration.

    Args:
        loop: A configured :class:`EvolutionLoop` instance.
    """

    def __init__(self, loop: object) -> None:
        from aiworker.autonomy.loop import EvolutionLoop as _EL
        if not isinstance(loop, _EL):
            raise TypeError(
                f"loop must be an EvolutionLoop instance, got {type(loop).__name__}"
            )
        self.loop: _EL = loop

    def evolve(
        self,
        goal: str,
        allowed_files: tuple[str, ...] = ("*.py",),
        max_iterations: int = 5,
        **kwargs: object,
    ) -> EvolutionResult:
        """Run the evolution loop for the given goal.

        Delegates directly to :meth:`EvolutionLoop.run`.

        Args:
            goal: The improvement target.
            allowed_files: Files the patch may modify.
            max_iterations: Iteration budget.
            **kwargs: Forwarded to ``loop.run()``.

        Returns:
            An immutable :class:`EvolutionResult`.
        """
        return self.loop.run(
            goal=goal,
            allowed_files=allowed_files,
            max_iterations=max_iterations,
            **kwargs,
        )
