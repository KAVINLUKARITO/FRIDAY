"""Prompt builder for DeepSeek code generation requests.

Constructs deterministic, structured prompts from planning context.
No side effects. No external calls.
"""
from __future__ import annotations
from typing import List, Optional


def build_generation_prompt(
    goal: str,
    plan_summary: str,
    allowed_files: List[str],
) -> str:
    """Build a code-generation prompt for DeepSeek.

    Args:
        goal: The change goal description.
        plan_summary: Human-readable plan summary string.
        allowed_files: List of files the patch is permitted to modify.

    Returns:
        A structured prompt string requesting JSON output.
    """
    files_str = ", ".join(allowed_files) if allowed_files else "any relevant file"

    return (
        "You are a senior software engineer generating a precise code patch.\n"
        "Respond with ONLY a JSON object — no markdown, no explanation.\n\n"
        f"Goal: {goal}\n"
        f"Plan: {plan_summary}\n"
        f"Allowed files: {files_str}\n\n"
        "Respond with this exact JSON structure:\n"
        "{\n"
        '  "analysis": "<one paragraph explaining the change>",\n'
        '  "diff": "<complete unified diff>",\n'
        '  "risk_score": <float 0.0 to 1.0>\n'
        "}\n\n"
        "Rules:\n"
        "- diff must be a valid unified diff format\n"
        "- risk_score: 0.0=trivial, 0.5=moderate, 1.0=critical\n"
        "- Only modify files listed in allowed_files\n"
        "- No explanation outside the JSON object"
    )
