"""Autonomous evolution controller for safe self-improvement.

Public API:
    EvolutionController — legacy orchestration entry point.
    EvolutionLoop — governance + learning integrated loop.
    AutonomyController — thin scheduling/trigger layer.
    EvolutionConfig — loop parameters.
    EvolutionState — iteration state snapshot.
    EvolutionResult — immutable outcome.
    AttemptRecord — per-attempt snapshot.
    PatchGenerator — protocol for injectable patch generation.
    StubPatchGenerator — deterministic stub for testing.
"""

from aiworker.autonomy.controller import (
    AutonomyController,
    EvolutionController,
    PatchGenerator,
    StubPatchGenerator,
    git_rollback,
)
from aiworker.autonomy.loop import EvolutionLoop
from aiworker.autonomy.models import (
    AttemptRecord,
    EvolutionConfig,
    EvolutionResult,
    EvolutionState,
)

__all__ = [
    "AutonomyController",
    "EvolutionController",
    "EvolutionConfig",
    "EvolutionLoop",
    "EvolutionResult",
    "EvolutionState",
    "AttemptRecord",
    "PatchGenerator",
    "StubPatchGenerator",
    "git_rollback",
]
