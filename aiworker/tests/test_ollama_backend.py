"""Tests for the OllamaBackend Ollama CLI integration.

Covers:
- Construction and parameter validation
- Property accessors
- GenerationBackend protocol compliance
- Successful generation via mocked subprocess
- Retry logic on transient failures
- RuntimeError after retry exhaustion
- Timeout handling
- FileNotFoundError handling (ollama not installed)
- OSError handling
- Non-zero exit code handling
- Environment variable restriction
- No global state across instances
- Deterministic subprocess invocation
- Output stripping behaviour
- Zero-retry mode (single attempt)
- Mixed failure/success retry sequences

Uses unittest only — no pytest dependency.
All subprocess calls are mocked — no real Ollama invocation.
"""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, call, patch as mock_patch

from aiworker.llm.ollama_backend import OllamaBackend


_SUBPROCESS_TARGET = "aiworker.llm.ollama_backend.subprocess.run"


def _mock_result(stdout: str = "model output", returncode: int = 0, stderr: str = "") -> MagicMock:
    """Create a mock subprocess.CompletedProcess."""
    mock = MagicMock()
    mock.stdout = stdout
    mock.returncode = returncode
    mock.stderr = stderr
    return mock


# ── Construction and validation ──────────────────────────────


class TestOllamaBackendConstruction(unittest.TestCase):
    """Verify constructor parameter validation."""

    def test_default_construction(self) -> None:
        backend = OllamaBackend()
        self.assertEqual(backend.model, "deepseek-coder:7b")
        self.assertEqual(backend.timeout, 120)
        self.assertEqual(backend.max_retries, 2)

    def test_custom_parameters(self) -> None:
        backend = OllamaBackend(
            model="codellama:13b",
            timeout=300,
            max_retries=5,
        )
        self.assertEqual(backend.model, "codellama:13b")
        self.assertEqual(backend.timeout, 300)
        self.assertEqual(backend.max_retries, 5)

    def test_empty_model_rejected(self) -> None:
        with self.assertRaises(ValueError):
            OllamaBackend(model="")

    def test_whitespace_model_rejected(self) -> None:
        with self.assertRaises(ValueError):
            OllamaBackend(model="   ")

    def test_zero_timeout_rejected(self) -> None:
        with self.assertRaises(ValueError):
            OllamaBackend(timeout=0)

    def test_negative_timeout_rejected(self) -> None:
        with self.assertRaises(ValueError):
            OllamaBackend(timeout=-1)

    def test_negative_max_retries_rejected(self) -> None:
        with self.assertRaises(ValueError):
            OllamaBackend(max_retries=-1)

    def test_zero_max_retries_allowed(self) -> None:
        backend = OllamaBackend(max_retries=0)
        self.assertEqual(backend.max_retries, 0)

    def test_timeout_boundary_one(self) -> None:
        backend = OllamaBackend(timeout=1)
        self.assertEqual(backend.timeout, 1)


# ── Protocol compliance ──────────────────────────────────────


class TestProtocolCompliance(unittest.TestCase):
    """Verify OllamaBackend satisfies GenerationBackend."""

    def test_satisfies_protocol(self) -> None:
        from aiworker.llm.deepseek_adapter import GenerationBackend
        backend = OllamaBackend()
        self.assertIsInstance(backend, GenerationBackend)

    def test_generate_signature(self) -> None:
        import inspect
        sig = inspect.signature(OllamaBackend.generate)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ["self", "prompt"])

    def test_generate_return_type_is_str(self) -> None:
        import inspect
        sig = inspect.signature(OllamaBackend.generate)
        self.assertEqual(sig.return_annotation, "str")


# ── Successful generation ────────────────────────────────────


class TestSuccessfulGeneration(unittest.TestCase):
    """Verify happy path with mocked subprocess."""

    @mock_patch(_SUBPROCESS_TARGET)
    def test_returns_stripped_stdout(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result(stdout="  model output  \n")
        backend = OllamaBackend()
        result = backend.generate("test prompt")
        self.assertEqual(result, "model output")

    @mock_patch(_SUBPROCESS_TARGET)
    def test_passes_prompt_via_stdin(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result()
        backend = OllamaBackend()
        backend.generate("hello world")
        call_kwargs = mock_run.call_args.kwargs
        self.assertEqual(call_kwargs["input"], "hello world")

    @mock_patch(_SUBPROCESS_TARGET)
    def test_uses_correct_command(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result()
        backend = OllamaBackend(model="deepseek-coder:7b")
        backend.generate("prompt")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd, ["ollama", "run", "deepseek-coder:7b"])

    @mock_patch(_SUBPROCESS_TARGET)
    def test_uses_custom_model(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result()
        backend = OllamaBackend(model="codellama:13b")
        backend.generate("prompt")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd, ["ollama", "run", "codellama:13b"])

    @mock_patch(_SUBPROCESS_TARGET)
    def test_captures_output_no_streaming(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result()
        backend = OllamaBackend()
        backend.generate("prompt")
        call_kwargs = mock_run.call_args.kwargs
        self.assertTrue(call_kwargs["capture_output"])
        self.assertTrue(call_kwargs["text"])

    @mock_patch(_SUBPROCESS_TARGET)
    def test_passes_timeout(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result()
        backend = OllamaBackend(timeout=60)
        backend.generate("prompt")
        call_kwargs = mock_run.call_args.kwargs
        self.assertEqual(call_kwargs["timeout"], 60)

    @mock_patch(_SUBPROCESS_TARGET)
    def test_empty_stdout_returns_empty_string(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result(stdout="")
        backend = OllamaBackend()
        result = backend.generate("prompt")
        self.assertEqual(result, "")

    @mock_patch(_SUBPROCESS_TARGET)
    def test_no_retry_on_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result()
        backend = OllamaBackend(max_retries=5)
        backend.generate("prompt")
        self.assertEqual(mock_run.call_count, 1)


# ── Retry logic ──────────────────────────────────────────────


class TestRetryLogic(unittest.TestCase):
    """Verify retry behaviour on transient failures."""

    @mock_patch(_SUBPROCESS_TARGET)
    def test_retries_on_nonzero_exit(self, mock_run: MagicMock) -> None:
        fail = _mock_result(returncode=1, stderr="model not loaded")
        success = _mock_result(stdout="good output")
        mock_run.side_effect = [fail, success]

        backend = OllamaBackend(max_retries=1)
        result = backend.generate("prompt")
        self.assertEqual(result, "good output")
        self.assertEqual(mock_run.call_count, 2)

    @mock_patch(_SUBPROCESS_TARGET)
    def test_retries_on_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd=["ollama"], timeout=60),
            _mock_result(stdout="recovered"),
        ]
        backend = OllamaBackend(max_retries=1)
        result = backend.generate("prompt")
        self.assertEqual(result, "recovered")

    @mock_patch(_SUBPROCESS_TARGET)
    def test_retries_on_file_not_found(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            FileNotFoundError("ollama not found"),
            _mock_result(stdout="found it"),
        ]
        backend = OllamaBackend(max_retries=1)
        result = backend.generate("prompt")
        self.assertEqual(result, "found it")

    @mock_patch(_SUBPROCESS_TARGET)
    def test_retries_on_os_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            OSError("permission denied"),
            _mock_result(stdout="ok"),
        ]
        backend = OllamaBackend(max_retries=1)
        result = backend.generate("prompt")
        self.assertEqual(result, "ok")

    @mock_patch(_SUBPROCESS_TARGET)
    def test_max_retries_respected(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result(returncode=1, stderr="error")
        backend = OllamaBackend(max_retries=3)
        with self.assertRaises(RuntimeError):
            backend.generate("prompt")
        # 1 initial + 3 retries = 4 total
        self.assertEqual(mock_run.call_count, 4)

    @mock_patch(_SUBPROCESS_TARGET)
    def test_zero_retries_single_attempt(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result(returncode=1, stderr="fail")
        backend = OllamaBackend(max_retries=0)
        with self.assertRaises(RuntimeError):
            backend.generate("prompt")
        self.assertEqual(mock_run.call_count, 1)

    @mock_patch(_SUBPROCESS_TARGET)
    def test_success_on_last_retry(self, mock_run: MagicMock) -> None:
        fails = [_mock_result(returncode=1, stderr="fail")] * 2
        mock_run.side_effect = fails + [_mock_result(stdout="finally")]
        backend = OllamaBackend(max_retries=2)
        result = backend.generate("prompt")
        self.assertEqual(result, "finally")
        self.assertEqual(mock_run.call_count, 3)


# ── Error raising after exhaustion ───────────────────────────


class TestExhaustedRetries(unittest.TestCase):
    """Verify RuntimeError is raised after all retries fail."""

    @mock_patch(_SUBPROCESS_TARGET)
    def test_raises_runtime_error(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result(
            returncode=1, stderr="model crash"
        )
        backend = OllamaBackend(max_retries=2)
        with self.assertRaises(RuntimeError) as ctx:
            backend.generate("prompt")
        self.assertIn("model crash", str(ctx.exception))

    @mock_patch(_SUBPROCESS_TARGET)
    def test_error_message_mentions_attempts(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result(returncode=1, stderr="err")
        backend = OllamaBackend(max_retries=2)
        with self.assertRaises(RuntimeError) as ctx:
            backend.generate("prompt")
        self.assertIn("3 attempt(s)", str(ctx.exception))

    @mock_patch(_SUBPROCESS_TARGET)
    def test_timeout_exhaustion_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["ollama"], timeout=30
        )
        backend = OllamaBackend(max_retries=1, timeout=30)
        with self.assertRaises(RuntimeError) as ctx:
            backend.generate("prompt")
        self.assertIn("timed out", str(ctx.exception))

    @mock_patch(_SUBPROCESS_TARGET)
    def test_file_not_found_exhaustion(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError("nope")
        backend = OllamaBackend(max_retries=0)
        with self.assertRaises(RuntimeError) as ctx:
            backend.generate("prompt")
        self.assertIn("not found", str(ctx.exception))

    @mock_patch(_SUBPROCESS_TARGET)
    def test_os_error_exhaustion(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = OSError("broken")
        backend = OllamaBackend(max_retries=0)
        with self.assertRaises(RuntimeError) as ctx:
            backend.generate("prompt")
        self.assertIn("broken", str(ctx.exception))


# ── Environment safety ───────────────────────────────────────


class TestEnvironmentSafety(unittest.TestCase):
    """Verify subprocess environment is restricted."""

    @mock_patch(_SUBPROCESS_TARGET)
    def test_env_only_allowlisted_keys(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result()
        backend = OllamaBackend()
        backend.generate("prompt")
        env = mock_run.call_args.kwargs.get("env", {})
        allowed = {"PATH", "HOME", "OLLAMA_HOST", "OLLAMA_MODELS"}
        for key in env:
            self.assertIn(key, allowed, f"Unexpected env var: {key}")

    def test_build_env_is_static(self) -> None:
        env1 = OllamaBackend._build_env()
        env2 = OllamaBackend._build_env()
        self.assertEqual(env1, env2)


# ── No global state ──────────────────────────────────────────


class TestNoGlobalState(unittest.TestCase):
    """Verify instances are fully isolated."""

    def test_separate_instances_no_shared_state(self) -> None:
        b1 = OllamaBackend(model="model-a", timeout=60, max_retries=1)
        b2 = OllamaBackend(model="model-b", timeout=120, max_retries=3)
        self.assertNotEqual(b1.model, b2.model)
        self.assertNotEqual(b1.timeout, b2.timeout)
        self.assertNotEqual(b1.max_retries, b2.max_retries)

    @mock_patch(_SUBPROCESS_TARGET)
    def test_generate_does_not_mutate_instance(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result()
        backend = OllamaBackend()
        model_before = backend.model
        timeout_before = backend.timeout
        retries_before = backend.max_retries
        backend.generate("prompt")
        self.assertEqual(backend.model, model_before)
        self.assertEqual(backend.timeout, timeout_before)
        self.assertEqual(backend.max_retries, retries_before)


# ── Determinism ──────────────────────────────────────────────


class TestDeterminism(unittest.TestCase):
    """Verify same inputs produce same subprocess calls."""

    @mock_patch(_SUBPROCESS_TARGET)
    def test_same_prompt_same_invocation(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_result(stdout="output")
        backend = OllamaBackend(model="test-model", timeout=30)
        backend.generate("hello")
        first_call = mock_run.call_args

        mock_run.reset_mock()
        mock_run.return_value = _mock_result(stdout="output")
        backend.generate("hello")
        second_call = mock_run.call_args

        self.assertEqual(first_call, second_call)


# ── Integration with RepairAdapter ───────────────────────────


class TestRepairAdapterIntegration(unittest.TestCase):
    """Verify OllamaBackend plugs into RepairAdapter."""

    @mock_patch(_SUBPROCESS_TARGET)
    def test_plugs_into_repair_adapter(self, mock_run: MagicMock) -> None:
        import json
        mock_run.return_value = _mock_result(
            stdout=json.dumps({
                "analysis": "found bug",
                "diff": "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x\n+y",
                "risk_score": 0.3,
            })
        )
        from aiworker.llm.deepseek_adapter import RepairAdapter
        from aiworker.reasoning.planner import ReasoningPlan

        backend = OllamaBackend()
        adapter = RepairAdapter(backend=backend)
        plan = ReasoningPlan(
            hypothesis="test",
            affected_modules=(),
            risk_score=0.3,
            strategy="fix",
        )
        response = adapter.generate(plan)
        self.assertTrue(response.valid)
        self.assertEqual(response.analysis, "found bug")


if __name__ == "__main__":
    unittest.main()
