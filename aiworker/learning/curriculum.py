"""Curriculum generator — converts abstract goals into ordered task sequences.

Deterministic decomposition. No LLM, no randomness.
"""
from __future__ import annotations
import uuid
from typing import List

from aiworker.learning.models import CurriculumTask


_SKILL_CURRICULUM: dict[str, list[tuple[str, str, str]]] = {
    "senior software development": [
        ("add proper type hints to all public functions", "typing", "beginner"),
        ("add context manager for resource cleanup", "design_pattern", "beginner"),
        ("refactor to use dependency injection pattern", "design_pattern", "intermediate"),
        ("add comprehensive error handling with custom exceptions", "error_handling", "intermediate"),
        ("add performance benchmark tests", "testing", "intermediate"),
        ("refactor to use strategy pattern for algorithm selection", "design_pattern", "advanced"),
        ("add thread-safety with proper locking primitives", "concurrency", "advanced"),
        ("add property-based tests using hypothesis", "testing", "advanced"),
    ],
    "testing": [
        ("add unit tests for all public methods", "testing", "beginner"),
        ("add edge case tests for boundary conditions", "testing", "beginner"),
        ("add integration tests for module interactions", "testing", "intermediate"),
        ("add performance regression tests", "testing", "intermediate"),
        ("add mutation testing coverage", "testing", "advanced"),
    ],
    "performance": [
        ("add timing instrumentation to hot paths", "performance", "beginner"),
        ("refactor to use generators instead of lists", "performance", "intermediate"),
        ("add caching layer with LRU eviction", "performance", "intermediate"),
        ("refactor to use async patterns for I/O bound operations", "performance", "advanced"),
    ],
    "default": [
        ("analyse and document existing code structure", "documentation", "beginner"),
        ("add type hints and docstrings", "typing", "beginner"),
        ("add unit test coverage", "testing", "intermediate"),
        ("refactor for readability and maintainability", "design_pattern", "intermediate"),
    ],
}


def generate_curriculum(learning_goal: str) -> List[CurriculumTask]:
    """Generate an ordered list of CurriculumTask from an abstract goal.

    Args:
        learning_goal: Plain-text goal e.g. "learn senior software development skills".

    Returns:
        Ordered list of CurriculumTask from beginner to advanced.
    """
    lower = learning_goal.lower()

    matched_key = "default"
    for key in _SKILL_CURRICULUM:
        if key in lower:
            matched_key = key
            break

    tasks = []
    for concrete_goal, skill_target, difficulty in _SKILL_CURRICULUM[matched_key]:
        tasks.append(CurriculumTask(
            task_id=str(uuid.uuid4()),
            learning_goal=learning_goal,
            concrete_goal=concrete_goal,
            skill_target=skill_target,
            difficulty=difficulty,
        ))
    return tasks


def next_task(tasks: List[CurriculumTask]) -> CurriculumTask | None:
    """Return the first incomplete task, ordered beginner → advanced."""
    order = {"beginner": 0, "intermediate": 1, "advanced": 2}
    pending = [t for t in tasks if not t.completed]
    if not pending:
        return None
    return min(pending, key=lambda t: order.get(t.difficulty, 99))
