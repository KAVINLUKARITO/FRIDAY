from __future__ import annotations

from typing import Any

from observability.logger import logger


def _score(result_summary: dict[str, Any], error: str | None) -> float:
    if error:
        return 0.0
    result_type = result_summary.get("type", "empty")
    if result_type == "empty":
        return 0.1
    base = {"text": 0.7, "list": 0.8, "dict": 0.9}.get(str(result_type), 0.6)
    if result_summary.get("key_info"):
        base = min(1.0, base + 0.05)
    return round(base, 2)


def evaluate(
    task: str,
    tool: str,
    arguments: dict[str, Any],
    result_summary: dict[str, Any],
    error: str | None,
) -> dict[str, Any]:
    try:
        _ = task
        _ = arguments
        score = _score(result_summary, error)
        if error is not None:
            verdict = {
                "score": score,
                "decision": "incorrect",
                "reason": "tool raised exception: " + str(error)[:100],
                "suggested_tool": "list_files",
            }
        elif result_summary.get("type") == "empty":
            verdict = {
                "score": score,
                "decision": "incorrect",
                "reason": "tool returned empty output",
                "suggested_tool": "list_files",
            }
        else:
            verdict = {
                "score": score,
                "decision": "correct",
                "reason": "tool returned non-empty " + str(result_summary.get("type", "unknown")) + " output",
                "suggested_tool": tool,
            }
        logger.log("CRITIC", "CRITIC_SCORE", verdict)
        return verdict
    except Exception:
        verdict = {
            "score": 0.0,
            "decision": "incorrect",
            "reason": "evaluator error",
            "suggested_tool": "list_files",
        }
        logger.log("CRITIC", "CRITIC_SCORE", verdict)
        return verdict
