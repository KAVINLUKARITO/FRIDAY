"""Plan validation logic.

Pure functions that verify structural correctness of a :class:`Plan`.
No side effects, no database access, no execution.
"""

from __future__ import annotations

from aiworker.planning.models import Plan, _VALID_RISK_LEVELS


def validate_plan(plan: Plan) -> bool:
    """Return ``True`` if *plan* is structurally valid.

    Checks:
    * At least one step.
    * Step IDs are sequential starting at 1.
    * Every step has a valid ``estimated_risk`` value.
    * ``complexity_score`` is in ``[0.0, 1.0]``.

    Args:
        plan: The :class:`Plan` to validate.

    Returns:
        ``True`` if all checks pass, ``False`` otherwise.
    """
    # At least one step
    if not plan.steps:
        return False

    # Sequential IDs starting at 1
    for idx, step in enumerate(plan.steps, start=1):
        if step.step_id != idx:
            return False

    # Valid risk levels
    for step in plan.steps:
        if step.estimated_risk not in _VALID_RISK_LEVELS:
            return False

    # Complexity score bounded
    if not (0.0 <= plan.complexity_score <= 1.0):
        return False

    return True
