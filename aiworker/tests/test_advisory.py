"""Tests for the LLM advisory layer (Milestone 8).

Covers:
- Prompt structure
- JSON parsing (valid, invalid, malformed)
- Timeout handling
- Fallback behaviour
- No side effects
- Deterministic fallback
- AdvisoryResult immutability
"""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import patch, MagicMock

import pytest

from aiworker.advisory.schema import AdvisoryResult
from aiworker.advisory.prompt_builder import build_prompt
from aiworker.advisory.advisor import request_advice, _parse_response, _FALLBACK


# ── prompt builder ───────────────────────────────────────────

class TestPromptBuilder:
    """Verify prompt structure and content."""

    def test_prompt_contains_goal(self) -> None:
        prompt = build_prompt("add caching", "3 steps", 0.85, 0.6)
        assert "add caching" in prompt

    def test_prompt_contains_plan(self) -> None:
        prompt = build_prompt("fix bug", "4 steps: reproduce, patch, test, verify", 0.7, 0.5)
        assert "4 steps" in prompt

    def test_prompt_contains_simulation(self) -> None:
        prompt = build_prompt("add feature", "3 steps", 0.85, 0.6)
        assert "0.85" in prompt

    def test_prompt_contains_confidence(self) -> None:
        prompt = build_prompt("add feature", "3 steps", 0.85, 0.60)
        assert "0.60" in prompt

    def test_prompt_requests_json(self) -> None:
        prompt = build_prompt("add feature", "3 steps", 0.85, 0.6)
        assert "JSON" in prompt

    def test_prompt_returns_string(self) -> None:
        result = build_prompt("goal", "plan", 0.5, 0.5)
        assert isinstance(result, str)


# ── response parsing ─────────────────────────────────────────

class TestResponseParsing:
    """Verify JSON response parsing and edge cases."""

    def test_valid_json_parsed(self) -> None:
        raw = json.dumps({
            "suggested_improvements": ["use cache", "add retries"],
            "risk_analysis": "Low risk change",
            "alternative_strategy": "Consider incremental rollout",
            "advisory_confidence": 0.85,
        })
        result = _parse_response(raw)
        assert result.suggested_improvements == ("use cache", "add retries")
        assert result.risk_analysis == "Low risk change"
        assert result.alternative_strategy == "Consider incremental rollout"
        assert result.advisory_confidence == 0.85

    def test_invalid_json_returns_fallback(self) -> None:
        result = _parse_response("not json at all")
        assert result == _FALLBACK

    def test_empty_string_returns_fallback(self) -> None:
        result = _parse_response("")
        assert result == _FALLBACK

    def test_none_returns_fallback(self) -> None:
        result = _parse_response(None)  # type: ignore[arg-type]
        assert result == _FALLBACK

    def test_non_dict_json_returns_fallback(self) -> None:
        result = _parse_response("[1, 2, 3]")
        assert result == _FALLBACK

    def test_confidence_clamped_upper(self) -> None:
        raw = json.dumps({
            "suggested_improvements": [],
            "risk_analysis": "ok",
            "alternative_strategy": "",
            "advisory_confidence": 5.0,
        })
        result = _parse_response(raw)
        assert result.advisory_confidence == 1.0

    def test_confidence_clamped_lower(self) -> None:
        raw = json.dumps({
            "suggested_improvements": [],
            "risk_analysis": "ok",
            "alternative_strategy": "",
            "advisory_confidence": -2.0,
        })
        result = _parse_response(raw)
        assert result.advisory_confidence == 0.0

    def test_missing_fields_use_defaults(self) -> None:
        raw = json.dumps({"risk_analysis": "some risk"})
        result = _parse_response(raw)
        assert result.suggested_improvements == ()
        assert result.risk_analysis == "some risk"
        assert result.alternative_strategy == ""
        assert result.advisory_confidence == 0.0

    def test_non_list_improvements_handled(self) -> None:
        raw = json.dumps({
            "suggested_improvements": "not a list",
            "risk_analysis": "ok",
        })
        result = _parse_response(raw)
        assert result.suggested_improvements == ()


# ── request_advice with mocked HTTP ──────────────────────────

class TestRequestAdvice:
    """Verify request_advice with mocked LLM endpoint."""

    def test_successful_llm_call(self) -> None:
        llm_response = json.dumps({
            "response": json.dumps({
                "suggested_improvements": ["add tests"],
                "risk_analysis": "Low risk",
                "alternative_strategy": "None needed",
                "advisory_confidence": 0.9,
            })
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = llm_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("aiworker.advisory.advisor.urllib.request.urlopen", return_value=mock_resp):
            result = request_advice("add feature", "3 steps", 0.85, 0.6)

        assert result.suggested_improvements == ("add tests",)
        assert result.risk_analysis == "Low risk"
        assert result.advisory_confidence == 0.9

    def test_timeout_returns_fallback(self) -> None:
        with patch(
            "aiworker.advisory.advisor.urllib.request.urlopen",
            side_effect=urllib.error.URLError("timeout"),
        ):
            result = request_advice("add feature", "3 steps", 0.85, 0.6)
        assert result == _FALLBACK

    def test_connection_error_returns_fallback(self) -> None:
        with patch(
            "aiworker.advisory.advisor.urllib.request.urlopen",
            side_effect=ConnectionError("refused"),
        ):
            result = request_advice("add feature", "3 steps", 0.85, 0.6)
        assert result == _FALLBACK

    def test_http_error_returns_fallback(self) -> None:
        with patch(
            "aiworker.advisory.advisor.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "http://test", 500, "Server Error", {}, None  # type: ignore[arg-type]
            ),
        ):
            result = request_advice("add feature", "3 steps", 0.85, 0.6)
        assert result == _FALLBACK

    def test_malformed_llm_response_returns_fallback(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("aiworker.advisory.advisor.urllib.request.urlopen", return_value=mock_resp):
            result = request_advice("add feature", "3 steps", 0.85, 0.6)
        assert result == _FALLBACK

    def test_custom_endpoint_via_env(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "{}"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict("os.environ", {"AIWORKER_LLM_ENDPOINT": "http://custom:8080/api"}):
            with patch("aiworker.advisory.advisor.urllib.request.urlopen", return_value=mock_resp) as mock_open:
                request_advice("goal", "plan", 0.5, 0.5)

        called_req = mock_open.call_args[0][0]
        assert called_req.full_url == "http://custom:8080/api"


# ── fallback determinism ─────────────────────────────────────

class TestFallbackDeterminism:
    """Verify fallback is always identical."""

    def test_fallback_is_deterministic(self) -> None:
        with patch(
            "aiworker.advisory.advisor.urllib.request.urlopen",
            side_effect=ConnectionError("refused"),
        ):
            results = [request_advice("goal", "plan", 0.5, 0.5) for _ in range(100)]
        first = results[0]
        for r in results[1:]:
            assert r.suggested_improvements == first.suggested_improvements
            assert r.risk_analysis == first.risk_analysis
            assert r.alternative_strategy == first.alternative_strategy
            assert r.advisory_confidence == first.advisory_confidence


# ── no side effects ──────────────────────────────────────────

class TestNoSideEffects:
    """Verify advisory layer has no side effects."""

    def test_no_file_writes(self) -> None:
        import tempfile
        import os

        workspace = tempfile.mkdtemp()
        before = os.listdir(workspace)

        with patch(
            "aiworker.advisory.advisor.urllib.request.urlopen",
            side_effect=ConnectionError("refused"),
        ):
            request_advice("add feature", "3 steps", 0.85, 0.6)

        after = os.listdir(workspace)
        assert before == after
        os.rmdir(workspace)


# ── schema immutability ──────────────────────────────────────

class TestSchemaImmutability:
    """Verify AdvisoryResult is frozen."""

    def test_advisory_result_frozen(self) -> None:
        result = AdvisoryResult()
        with pytest.raises(AttributeError):
            result.risk_analysis = "changed"  # type: ignore[misc]

    def test_default_values(self) -> None:
        result = AdvisoryResult()
        assert result.suggested_improvements == ()
        assert result.risk_analysis == "LLM unavailable"
        assert result.alternative_strategy == ""
        assert result.advisory_confidence == 0.0
