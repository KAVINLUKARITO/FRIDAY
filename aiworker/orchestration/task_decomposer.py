"""Deterministic task decomposition for architecture execution."""

from __future__ import annotations

from aiworker.orchestration.architecture_models import (
    ArchitectureBlueprint,
    AtomicTask,
    RiskLevel,
)


_HIGH_RISK_MODULES = {
    "architecture_controller.py",
    "topology_guard.py",
    "schema_guard.py",
}

_MEDIUM_RISK_MODULES = {
    "failure_classifier.py",
    "retry_policy.py",
    "confidence_engine.py",
}


def _risk_for_module(module_name: str) -> RiskLevel:
    if module_name in _HIGH_RISK_MODULES:
        return RiskLevel.HIGH
    if module_name in _MEDIUM_RISK_MODULES:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def decompose_blueprint(blueprint: ArchitectureBlueprint) -> list[AtomicTask]:
    """Create isolated atomic tasks from blueprint execution order."""
    known_modules = set(blueprint.modules_to_create)
    tasks: list[AtomicTask] = []

    for module_name in blueprint.execution_order:
        if module_name not in known_modules:
            continue
        tasks.append(
            AtomicTask(
                module=module_name,
                responsibility=f"Implement and validate {module_name}",
                allowed_files=(f"aiworker/orchestration/{module_name}",),
                risk_level=_risk_for_module(module_name),
            )
        )

    return tasks
