"""LLM advisory client.

Calls an external LLM endpoint via HTTP and returns a structured
:class:`AdvisoryResult`.  Falls back to deterministic defaults on any
failure.  Advisory only — no execution, no approval, no file writes.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error

from aiworker.advisory.prompt_builder import build_prompt
from aiworker.advisory.schema import AdvisoryResult

_DEFAULT_ENDPOINT = "http://localhost:11434/api/generate"
_TIMEOUT_SECONDS = 30

_FALLBACK = AdvisoryResult(
    suggested_improvements=(),
    risk_analysis="LLM unavailable",
    alternative_strategy="",
    advisory_confidence=0.0,
)


def _parse_response(raw: str) -> AdvisoryResult:
    """Parse an LLM JSON response into an :class:`AdvisoryResult`.

    Returns the deterministic fallback if parsing fails or values are
    out of range.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _FALLBACK

    if not isinstance(data, dict):
        return _FALLBACK

    improvements = data.get("suggested_improvements", [])
    if not isinstance(improvements, list):
        improvements = []
    improvements = tuple(str(s) for s in improvements)

    risk = str(data.get("risk_analysis", "LLM unavailable"))
    alt = str(data.get("alternative_strategy", ""))

    try:
        conf = float(data.get("advisory_confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    return AdvisoryResult(
        suggested_improvements=improvements,
        risk_analysis=risk,
        alternative_strategy=alt,
        advisory_confidence=conf,
    )


def request_advice(
    goal: str,
    plan_summary: str,
    simulation_success: float,
    confidence_score: float,
) -> AdvisoryResult:
    """Request advisory guidance from an external LLM.

    The LLM endpoint is read from the ``AIWORKER_LLM_ENDPOINT``
    environment variable (defaults to ``http://localhost:11434/api/generate``).

    On **any** failure (network, timeout, parse error) the function
    returns a deterministic fallback result.  This function never
    raises exceptions to callers.

    Args:
        goal: The original goal description.
        plan_summary: Human-readable plan summary.
        simulation_success: Simulated success probability ``[0, 1]``.
        confidence_score: Historical confidence score ``[0, 1]``.

    Returns:
        An :class:`AdvisoryResult` — either from the LLM or the
        deterministic fallback.
    """
    endpoint = os.environ.get("AIWORKER_LLM_ENDPOINT", _DEFAULT_ENDPOINT)

    prompt = build_prompt(goal, plan_summary, simulation_success, confidence_score)

    payload = json.dumps({
        "prompt": prompt,
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode()
    except Exception:
        return _FALLBACK

    # Try to extract the response text from common LLM API formats.
    try:
        envelope = json.loads(body)
        if isinstance(envelope, dict):
            text = envelope.get("response") or envelope.get("text") or body
        else:
            text = body
    except (json.JSONDecodeError, TypeError):
        text = body

    return _parse_response(text)
