"""Core models for the architecture orchestration engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional


class RiskLevel(Enum):
    """Risk level for an atomic task."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FailureType(Enum):
    """Deterministic failure classes from sandbox execution."""

    SyntaxError = "syntax_error"
    ImportError = "import_error"
    TestFailure = "test_failure"
    MissingFile = "missing_file"
    Timeout = "timeout"
    Unknown = "unknown"


class ModelRole(Enum):
    """Role-separated model slots for architecture execution."""

    Planner = "planner"
    Generator = "generator"
    Corrector = "corrector"


class ControllerState(Enum):
    """State machine states for architecture controller execution."""

    INITIALIZED = "initialized"
    PLANNING = "planning"
    DECOMPOSING = "decomposing"
    EXECUTING_TASK = "executing_task"
    COMPLETED = "completed"
    MAX_ATTEMPTS_REACHED = "max_attempts_reached"
    CIRCUIT_OPEN = "circuit_open"


@dataclass(frozen=True)
class ArchitectureBlueprint:
    """Structured deterministic architecture blueprint."""

    modules_to_create: tuple[str, ...]
    interfaces: tuple[str, ...]
    dependencies: tuple[str, ...]
    execution_order: tuple[str, ...]


@dataclass(frozen=True)
class AtomicTask:
    """Single isolated architecture task."""

    module: str
    responsibility: str
    allowed_files: tuple[str, ...]
    risk_level: RiskLevel


@dataclass(frozen=True)
class ValidatedPatch:
    """Schema-validated patch payload."""

    analysis: str
    diff: str
    risk_score: float


@dataclass(frozen=True)
class ValidationResult:
    """Result of schema validation for generated payload."""

    is_valid: bool
    error: Optional[str]
    patch: Optional[ValidatedPatch]


@dataclass(frozen=True)
class GuardDecision:
    """Decision from topology guard."""

    allowed: bool
    reason: str
    touched_files: tuple[str, ...]
    package_roots: tuple[str, ...]


@dataclass(frozen=True)
class SandboxResult:
    """Deterministic sandbox execution result for one patch attempt."""

    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    tests_passed: int = 0
    tests_total: int = 0
    import_errors: int = 0
    runtime_exceptions: int = 0
    missing_files: tuple[str, ...] = ()
    timed_out: bool = False


@dataclass(frozen=True)
class AttemptRecord:
    """Single task attempt execution record."""

    task_module: str
    attempt_number: int
    accepted: bool
    failure_type: Optional[FailureType]
    failure_instruction: str
    confidence: float


@dataclass(frozen=True)
class ControllerRunReport:
    """Final architecture controller run output."""

    state: ControllerState
    completed_tasks: tuple[str, ...]
    failed_tasks: tuple[str, ...]
    attempts: tuple[AttemptRecord, ...]


@dataclass(frozen=True)
class ControllerConfig:
    """Configuration for deterministic controller behavior."""

    max_attempts_per_task: int = 3
    circuit_breaker_threshold: int = 5
    confidence_threshold: float = 0.75
    base_seed: int = 0
    repo_root: str = "."


@dataclass(frozen=True)
class ModelRoleConfig:
    """Role-to-model mapping for strict model separation."""

    role_to_model: Mapping[ModelRole, str]

    def model_for(self, role: ModelRole) -> str:
        """Return model name for role, raising if role is unmapped."""
        if role not in self.role_to_model:
            raise KeyError(f"Model role is not configured: {role.value}")
        return self.role_to_model[role]
