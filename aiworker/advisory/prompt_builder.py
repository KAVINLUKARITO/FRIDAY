"""Structured prompt builder for the LLM advisory layer.

Constructs a concise prompt from planning, simulation, and scoring
inputs.  No side effects, no external calls.
"""

from __future__ import annotations


def build_prompt(
    goal: str,
    plan_summary: str,
    simulation_success: float,
    confidence_score: float,
) -> str:
    """Build a structured prompt for the LLM advisory endpoint.

    The prompt summarises the current analysis state and requests a
    JSON response with specific advisory fields.

    Args:
        goal: The original goal description.
        plan_summary: Human-readable summary of the generated plan.
        simulation_success: Estimated success probability ``[0, 1]``.
        confidence_score: Historical confidence score ``[0, 1]``.

    Returns:
        A prompt string ready to send to an LLM endpoint.
    """
    return (
        "You are a code-change risk advisor. "
        "Analyse the following proposed change and respond with ONLY "
        "a JSON object (no markdown, no explanation).\n\n"
        f"Goal: {goal}\n"
        f"Plan: {plan_summary}\n"
        f"Simulated success probability: {simulation_success:.2f}\n"
        f"Historical confidence score: {confidence_score:.2f}\n\n"
        "Respond with this exact JSON structure:\n"
        "{\n"
        '  "suggested_improvements": ["<improvement1>", ...],\n'
        '  "risk_analysis": "<one paragraph>",\n'
        '  "alternative_strategy": "<one paragraph>",\n'
        '  "advisory_confidence": <float 0-1>\n'
        "}"
    )
