"""Tests for the LLM backend layer — OllamaBackend + DeepSeekAdapter.

Covers:
- Constructor validation (all parameters)
- OllamaBackend: generate() with mocked subprocess
- OllamaBackend: timeout, retry, missing executable error messages
- OllamaBackend: environment variable restriction
- DeepSeekAdapter: constructor validation
- DeepSeekAdapter: generate() with mock backend
- DeepSeekAdapter: returns None on backend failure
- DeepSeekAdapter: returns None on invalid response
- _validate_response: all valid/invalid permutations
- DeepSeekResponse: frozen, to_dict structure
"""
from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

from aiworker.llm.backend import GenerationBackend
from aiworker.llm.ollama_backend import OllamaBackend, _safe_env
from aiworker.llm.deepseek_adapter import DeepSeekAdapter
from aiworker.llm.response import DeepSeekResponse, _validate_response
from aiworker.llm.prompt_builder import build_generation_prompt


# ── Helpers ──────────────────────────────────────────────────────────────────

def _valid_raw() -> str:
    return json.dumps({
        "analysis": "Adds a multiply function with type hints.",
        "diff": "--- a/math.py\n+++ b/math.py\n@@ -1 +1,4 @@\n+def mul(a,b): return a*b\n",
        "risk_score": 0.1,
    })


class _MockBackend(GenerationBackend):
    def __init__(self, response: str = "", raise_exc=None):
        self._response = response
        self._raise = raise_exc
        self.calls = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self._raise:
            raise self._raise
        return self._response


# ── OllamaBackend Constructor ────────────────────────────────────────────────

class TestOllamaBackendConstructor(unittest.TestCase):
    def test_defaults(self):
        ob = OllamaBackend()
        self.assertEqual(ob.model, "deepseek-coder:7b")
        self.assertEqual(ob.timeout, 120)
        self.assertEqual(ob.max_retries, 2)

    def test_custom_values(self):
        ob = OllamaBackend(model="llama3:8b", timeout=60, max_retries=0)
        self.assertEqual(ob.model, "llama3:8b")
        self.assertEqual(ob.timeout, 60)
        self.assertEqual(ob.max_retries, 0)

    def test_empty_model_raises(self):
        with self.assertRaises(ValueError):
            OllamaBackend(model="")

    def test_whitespace_model_raises(self):
        with self.assertRaises(ValueError):
            OllamaBackend(model="   ")

    def test_zero_timeout_raises(self):
        with self.assertRaises(ValueError):
            OllamaBackend(timeout=0)

    def test_negative_timeout_raises(self):
        with self.assertRaises(ValueError):
            OllamaBackend(timeout=-1)

    def test_negative_retries_raises(self):
        with self.assertRaises(ValueError):
            OllamaBackend(max_retries=-1)

    def test_zero_retries_allowed(self):
        ob = OllamaBackend(max_retries=0)
        self.assertEqual(ob.max_retries, 0)

    def test_model_stripped(self):
        ob = OllamaBackend(model="  mymodel  ")
        self.assertEqual(ob.model, "mymodel")

    def test_to_dict_structure(self):
        ob = OllamaBackend()
        d = ob.to_dict()
        self.assertIn("backend", d)
        self.assertIn("model", d)
        self.assertIn("timeout", d)
        self.assertIn("max_retries", d)
        self.assertEqual(d["backend"], "ollama")


# ── OllamaBackend generate() ─────────────────────────────────────────────────

class TestOllamaBackendGenerate(unittest.TestCase):

    def _mock_popen(self, stdout=b"response text", returncode=0, stderr=b""):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (stdout, stderr)
        mock_proc.returncode = returncode
        return mock_proc

    def test_successful_generation(self):
        ob = OllamaBackend(max_retries=0)
        mock_proc = self._mock_popen(stdout=b"hello world")
        with patch("shutil.which", return_value="/usr/bin/ollama"):
            with patch("subprocess.Popen", return_value=mock_proc):
                result = ob.generate("test prompt")
        self.assertEqual(result, "hello world")

    def test_prompt_sent_via_stdin(self):
        ob = OllamaBackend(max_retries=0)
        mock_proc = self._mock_popen(stdout=b"ok")
        with patch("shutil.which", return_value="/usr/bin/ollama"):
            with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                ob.generate("my prompt")
        mock_proc.communicate.assert_called_once()
        args = mock_proc.communicate.call_args
        self.assertEqual(args[1]["input"], b"my prompt")

    def test_nonzero_returncode_raises(self):
        ob = OllamaBackend(max_retries=0)
        mock_proc = self._mock_popen(returncode=1, stderr=b"error occurred")
        with patch("shutil.which", return_value="/usr/bin/ollama"):
            with patch("subprocess.Popen", return_value=mock_proc):
                with self.assertRaises(RuntimeError) as ctx:
                    ob.generate("prompt")
        self.assertIn("attempt", str(ctx.exception).lower())

    def test_missing_executable_raises_with_not_found(self):
        ob = OllamaBackend(max_retries=0)
        with patch("shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                ob.generate("prompt")
        self.assertIn("not found", str(ctx.exception).lower())

    def test_timeout_raises_runtime_error(self):
        ob = OllamaBackend(timeout=1, max_retries=0)
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="ollama", timeout=1)
        mock_proc.kill = MagicMock()
        with patch("shutil.which", return_value="/usr/bin/ollama"):
            with patch("subprocess.Popen", return_value=mock_proc):
                with self.assertRaises(RuntimeError) as ctx:
                    ob.generate("prompt")
        self.assertIn("attempt", str(ctx.exception))

    def test_error_message_includes_attempt_count(self):
        ob = OllamaBackend(max_retries=2)
        mock_proc = self._mock_popen(returncode=1, stderr=b"fail")
        with patch("shutil.which", return_value="/usr/bin/ollama"):
            with patch("subprocess.Popen", return_value=mock_proc):
                with patch("time.sleep"):  # skip backoff
                    with self.assertRaises(RuntimeError) as ctx:
                        ob.generate("prompt")
        err = str(ctx.exception)
        # Must include attempt count (3 total: 1 original + 2 retries)
        self.assertIn("3 attempt", err)

    def test_retry_attempts_correct_count(self):
        ob = OllamaBackend(max_retries=2)
        call_count = {"n": 0}

        def mock_popen(*args, **kwargs):
            call_count["n"] += 1
            proc = self._mock_popen(returncode=1, stderr=b"err")
            return proc

        with patch("shutil.which", return_value="/usr/bin/ollama"):
            with patch("subprocess.Popen", side_effect=mock_popen):
                with patch("time.sleep"):
                    with self.assertRaises(RuntimeError):
                        ob.generate("prompt")
        self.assertEqual(call_count["n"], 3)  # 1 original + 2 retries

    def test_success_on_second_attempt(self):
        ob = OllamaBackend(max_retries=1)
        attempt = {"n": 0}

        def mock_popen(*args, **kwargs):
            attempt["n"] += 1
            if attempt["n"] == 1:
                return self._mock_popen(returncode=1, stderr=b"fail")
            return self._mock_popen(stdout=b"success on retry")

        with patch("shutil.which", return_value="/usr/bin/ollama"):
            with patch("subprocess.Popen", side_effect=mock_popen):
                with patch("time.sleep"):
                    result = ob.generate("prompt")
        self.assertEqual(result, "success on retry")


# ── _safe_env ────────────────────────────────────────────────────────────────

class TestSafeEnv(unittest.TestCase):
    def test_only_allowed_vars(self):
        fake_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "SECRET_KEY": "should-be-excluded",
            "OLLAMA_HOST": "localhost:11434",
            "OLLAMA_MODELS": "/models",
            "AWS_ACCESS_KEY": "excluded",
        }
        with patch.dict("os.environ", fake_env, clear=True):
            env = _safe_env()
        self.assertIn("PATH", env)
        self.assertIn("HOME", env)
        self.assertIn("OLLAMA_HOST", env)
        self.assertIn("OLLAMA_MODELS", env)
        self.assertNotIn("SECRET_KEY", env)
        self.assertNotIn("AWS_ACCESS_KEY", env)


# ── _validate_response ───────────────────────────────────────────────────────

class TestValidateResponse(unittest.TestCase):
    def test_valid_response(self):
        result = _validate_response(_valid_raw())
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, [])

    def test_empty_string_returns_invalid(self):
        result = _validate_response("")
        self.assertFalse(result.valid)
        self.assertTrue(len(result.errors) > 0)

    def test_none_returns_invalid(self):
        result = _validate_response(None)
        self.assertFalse(result.valid)

    def test_non_json_returns_invalid(self):
        result = _validate_response("not json at all")
        self.assertFalse(result.valid)
        self.assertTrue(any("JSON" in e for e in result.errors))

    def test_markdown_fenced_json_parsed(self):
        raw = "```json\n" + _valid_raw() + "\n```"
        result = _validate_response(raw)
        self.assertTrue(result.valid)

    def test_missing_analysis_key_invalid(self):
        data = json.dumps({"diff": "--- a\n+++ b\n@@ @@\n+x\n", "risk_score": 0.5})
        result = _validate_response(data)
        self.assertFalse(result.valid)
        self.assertTrue(any("analysis" in e for e in result.errors))

    def test_missing_diff_key_invalid(self):
        data = json.dumps({"analysis": "ok", "risk_score": 0.5})
        result = _validate_response(data)
        self.assertFalse(result.valid)

    def test_missing_risk_score_invalid(self):
        data = json.dumps({"analysis": "ok", "diff": "--- a\n+++ b\n@@ @@\n+x\n"})
        result = _validate_response(data)
        self.assertFalse(result.valid)

    def test_empty_diff_invalid(self):
        data = json.dumps({"analysis": "ok", "diff": "", "risk_score": 0.5})
        result = _validate_response(data)
        self.assertFalse(result.valid)
        self.assertTrue(any("diff" in e for e in result.errors))

    def test_whitespace_diff_invalid(self):
        data = json.dumps({"analysis": "ok", "diff": "   ", "risk_score": 0.5})
        result = _validate_response(data)
        self.assertFalse(result.valid)

    def test_risk_score_above_1_invalid(self):
        data = json.dumps({"analysis": "ok", "diff": "--- a\n+++ b\n@@ @@\n+x\n", "risk_score": 1.5})
        result = _validate_response(data)
        self.assertFalse(result.valid)

    def test_risk_score_below_0_invalid(self):
        data = json.dumps({"analysis": "ok", "diff": "--- a\n+++ b\n@@ @@\n+x\n", "risk_score": -0.1})
        result = _validate_response(data)
        self.assertFalse(result.valid)

    def test_risk_score_exactly_0_valid(self):
        data = json.dumps({"analysis": "ok", "diff": "--- a\n+++ b\n@@ @@\n+x\n", "risk_score": 0.0})
        result = _validate_response(data)
        self.assertTrue(result.valid)

    def test_risk_score_exactly_1_valid(self):
        data = json.dumps({"analysis": "ok", "diff": "--- a\n+++ b\n@@ @@\n+x\n", "risk_score": 1.0})
        result = _validate_response(data)
        self.assertTrue(result.valid)

    def test_non_dict_json_invalid(self):
        result = _validate_response("[1, 2, 3]")
        self.assertFalse(result.valid)

    def test_analysis_preserved(self):
        result = _validate_response(_valid_raw())
        self.assertIn("multiply", result.analysis)

    def test_diff_preserved(self):
        result = _validate_response(_valid_raw())
        self.assertIn("math.py", result.diff)

    def test_risk_score_preserved(self):
        result = _validate_response(_valid_raw())
        self.assertAlmostEqual(result.risk_score, 0.1)


# ── DeepSeekResponse ─────────────────────────────────────────────────────────

class TestDeepSeekResponse(unittest.TestCase):
    def test_frozen(self):
        r = DeepSeekResponse(valid=True, analysis="a", diff="d", risk_score=0.1)
        with self.assertRaises((AttributeError, TypeError)):
            r.valid = False

    def test_to_dict_structure(self):
        r = DeepSeekResponse(valid=True, analysis="a", diff="d", risk_score=0.2, errors=[])
        d = r.to_dict()
        for k in ("valid", "analysis", "diff", "risk_score", "errors"):
            self.assertIn(k, d)

    def test_errors_default_empty(self):
        r = DeepSeekResponse(valid=True, analysis="a", diff="d", risk_score=0.0)
        self.assertEqual(r.errors, [])


# ── DeepSeekAdapter Constructor ───────────────────────────────────────────────

class TestDeepSeekAdapterConstructor(unittest.TestCase):
    def test_defaults_with_mock_backend(self):
        adapter = DeepSeekAdapter(backend=_MockBackend())
        self.assertEqual(adapter.model_name, "deepseek-coder:7b")
        self.assertEqual(adapter.temperature, 0.0)
        self.assertEqual(adapter.max_tokens, 4096)
        self.assertEqual(adapter.timeout, 120)
        self.assertEqual(adapter.max_retries, 2)

    def test_empty_model_name_raises(self):
        with self.assertRaises(ValueError):
            DeepSeekAdapter(backend=_MockBackend(), model_name="")

    def test_whitespace_model_raises(self):
        with self.assertRaises(ValueError):
            DeepSeekAdapter(backend=_MockBackend(), model_name="   ")

    def test_temperature_above_2_raises(self):
        with self.assertRaises(ValueError):
            DeepSeekAdapter(backend=_MockBackend(), temperature=2.1)

    def test_temperature_below_0_raises(self):
        with self.assertRaises(ValueError):
            DeepSeekAdapter(backend=_MockBackend(), temperature=-0.1)

    def test_temperature_exactly_0_allowed(self):
        a = DeepSeekAdapter(backend=_MockBackend(), temperature=0.0)
        self.assertEqual(a.temperature, 0.0)

    def test_temperature_exactly_2_allowed(self):
        a = DeepSeekAdapter(backend=_MockBackend(), temperature=2.0)
        self.assertEqual(a.temperature, 2.0)

    def test_zero_max_tokens_raises(self):
        with self.assertRaises(ValueError):
            DeepSeekAdapter(backend=_MockBackend(), max_tokens=0)

    def test_negative_max_tokens_raises(self):
        with self.assertRaises(ValueError):
            DeepSeekAdapter(backend=_MockBackend(), max_tokens=-1)

    def test_zero_timeout_raises(self):
        with self.assertRaises(ValueError):
            DeepSeekAdapter(backend=_MockBackend(), timeout=0)

    def test_negative_timeout_raises(self):
        with self.assertRaises(ValueError):
            DeepSeekAdapter(backend=_MockBackend(), timeout=-5)

    def test_negative_retries_raises(self):
        with self.assertRaises(ValueError):
            DeepSeekAdapter(backend=_MockBackend(), max_retries=-1)

    def test_zero_retries_allowed(self):
        a = DeepSeekAdapter(backend=_MockBackend(), max_retries=0)
        self.assertEqual(a.max_retries, 0)

    def test_custom_backend_used(self):
        mock = _MockBackend(_valid_raw())
        a = DeepSeekAdapter(backend=mock)
        self.assertIs(a._backend, mock)

    def test_to_dict_structure(self):
        a = DeepSeekAdapter(backend=_MockBackend())
        d = a.to_dict()
        for k in ("adapter", "model_name", "temperature", "max_tokens", "timeout", "max_retries"):
            self.assertIn(k, d)


# ── DeepSeekAdapter generate() ────────────────────────────────────────────────

class _SimplePlan:
    def __init__(self, goal, steps=()):
        self.goal = goal
        self.steps = steps

class _Step:
    def __init__(self, description):
        self.description = description


class TestDeepSeekAdapterGenerate(unittest.TestCase):
    def _adapter(self, response=None):
        raw = response if response is not None else _valid_raw()
        return DeepSeekAdapter(backend=_MockBackend(raw))

    def test_returns_response_on_valid_output(self):
        a = self._adapter()
        result = a.generate(_SimplePlan("add multiply"))
        self.assertIsNotNone(result)
        self.assertIsInstance(result, DeepSeekResponse)
        self.assertTrue(result.valid)

    def test_returns_none_on_backend_failure(self):
        a = DeepSeekAdapter(backend=_MockBackend(raise_exc=RuntimeError("backend down")))
        result = a.generate(_SimplePlan("add multiply"))
        self.assertIsNone(result)

    def test_returns_none_on_invalid_json(self):
        a = DeepSeekAdapter(backend=_MockBackend("not json"))
        result = a.generate(_SimplePlan("add multiply"))
        self.assertIsNone(result)

    def test_returns_none_on_missing_diff(self):
        raw = json.dumps({"analysis": "ok", "diff": "", "risk_score": 0.5})
        a = DeepSeekAdapter(backend=_MockBackend(raw))
        result = a.generate(_SimplePlan("add multiply"))
        self.assertIsNone(result)

    def test_goal_override_takes_priority(self):
        mock = _MockBackend(_valid_raw())
        a = DeepSeekAdapter(backend=mock)
        a.generate(_SimplePlan("plan goal"), goal="override goal")
        # Check that override goal appears in prompt
        self.assertIn("override goal", mock.calls[0])

    def test_allowed_files_passed_to_prompt(self):
        mock = _MockBackend(_valid_raw())
        a = DeepSeekAdapter(backend=mock)
        a.generate(_SimplePlan("goal"), allowed_files=["math.py", "test_math.py"])
        self.assertIn("math.py", mock.calls[0])

    def test_plan_steps_in_prompt(self):
        mock = _MockBackend(_valid_raw())
        a = DeepSeekAdapter(backend=mock)
        plan = _SimplePlan("goal", steps=[_Step("Analyse"), _Step("Implement")])
        a.generate(plan)
        self.assertIn("Analyse", mock.calls[0])
        self.assertIn("Implement", mock.calls[0])

    def test_string_plan_accepted(self):
        a = self._adapter()
        result = a.generate("add feature directly as string")
        self.assertIsNotNone(result)

    def test_none_plan_returns_none(self):
        a = self._adapter()
        result = a.generate(None)
        self.assertIsNone(result)

    def test_backend_called_exactly_once_on_success(self):
        mock = _MockBackend(_valid_raw())
        a = DeepSeekAdapter(backend=mock)
        a.generate(_SimplePlan("goal"))
        self.assertEqual(len(mock.calls), 1)


# ── Prompt Builder ────────────────────────────────────────────────────────────

class TestPromptBuilder(unittest.TestCase):
    def test_contains_goal(self):
        p = build_generation_prompt("add caching", "3 steps", ["cache.py"])
        self.assertIn("add caching", p)

    def test_contains_allowed_files(self):
        p = build_generation_prompt("goal", "plan", ["math.py", "test.py"])
        self.assertIn("math.py", p)
        self.assertIn("test.py", p)

    def test_requests_json(self):
        p = build_generation_prompt("goal", "plan", [])
        self.assertIn("JSON", p)

    def test_contains_required_keys(self):
        p = build_generation_prompt("goal", "plan", [])
        self.assertIn("analysis", p)
        self.assertIn("diff", p)
        self.assertIn("risk_score", p)

    def test_empty_allowed_files(self):
        p = build_generation_prompt("goal", "plan", [])
        self.assertIsInstance(p, str)
        self.assertGreater(len(p), 0)


if __name__ == "__main__":
    unittest.main()
