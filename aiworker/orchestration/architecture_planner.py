"""Deterministic architectural planner."""

from __future__ import annotations

from aiworker.orchestration.architecture_models import ArchitectureBlueprint


_DEFAULT_MODULES: tuple[str, ...] = (
    "architecture_models.py",
    "architecture_planner.py",
    "task_decomposer.py",
    "patch_interface.py",
    "schema_guard.py",
    "failure_classifier.py",
    "retry_policy.py",
    "confidence_engine.py",
    "topology_guard.py",
    "architecture_controller.py",
    "integration_tests.py",
)

_DEFAULT_INTERFACES: tuple[str, ...] = (
    "PatchGenerator.generate(plan, goal, allowed_files, seed) -> str | None",
    "SandboxRunner.run(diff, allowed_files) -> SandboxResult",
    "ArchitectureController.execute(goal) -> ControllerRunReport",
)

_DEFAULT_DEPENDENCIES: tuple[str, ...] = (
    "architecture_planner -> task_decomposer",
    "task_decomposer -> patch_interface",
    "patch_interface -> schema_guard",
    "schema_guard -> topology_guard",
    "topology_guard -> sandbox runner",
    "sandbox runner -> failure_classifier",
    "failure_classifier -> retry_policy",
    "sandbox runner + schema_guard -> confidence_engine",
    "all modules -> architecture_controller",
)

_DEFAULT_EXECUTION_ORDER: tuple[str, ...] = (
    "architecture_models.py",
    "architecture_planner.py",
    "task_decomposer.py",
    "patch_interface.py",
    "schema_guard.py",
    "failure_classifier.py",
    "retry_policy.py",
    "confidence_engine.py",
    "topology_guard.py",
    "architecture_controller.py",
    "integration_tests.py",
)


def create_blueprint(goal: str) -> ArchitectureBlueprint:
    """Create a deterministic architecture blueprint from a goal string."""
    normalized_goal = " ".join(goal.strip().split()).lower()

    modules = _DEFAULT_MODULES
    if "test" in normalized_goal and "integration_tests.py" not in modules:
        modules = modules + ("integration_tests.py",)

    return ArchitectureBlueprint(
        modules_to_create=modules,
        interfaces=_DEFAULT_INTERFACES,
        dependencies=_DEFAULT_DEPENDENCIES,
        execution_order=_DEFAULT_EXECUTION_ORDER,
    )
