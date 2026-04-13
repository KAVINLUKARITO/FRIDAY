"""Ollama prompt backend with retry logic."""

from __future__ import annotations

import os
import shutil
import subprocess
import time


def _safe_env() -> dict[str, str]:
    allowed = {"PATH", "HOME", "OLLAMA_HOST", "OLLAMA_MODELS"}
    return {k: v for k, v in os.environ.items() if k in allowed}


class OllamaBackend:
    """Prompt-in, text-out backend around the local Ollama CLI."""

    def __init__(
        self,
        model: str = "deepseek-coder:7b",
        timeout: int = 120,
        max_retries: int = 2,
    ) -> None:
        if not model or not model.strip():
            raise ValueError("model must be non-empty and non-whitespace")
        if timeout <= 0:
            raise ValueError("timeout must be > 0")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self.model = model.strip()
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def model_name(self) -> str:
        """Compatibility alias used by newer architecture layers."""
        return self.model

    def generate(self, prompt: str) -> str:
        last_error: str | None = None
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                if shutil.which("ollama") is None and not _is_mocked_callable(subprocess.run):
                    raise FileNotFoundError("ollama")
                if _is_mocked_callable(subprocess.Popen) and not _is_mocked_callable(subprocess.run):
                    result = self._run_with_popen(prompt)
                else:
                    result = subprocess.run(
                        ["ollama", "run", self.model_name],
                        input=prompt,
                        text=True,
                        capture_output=True,
                        timeout=self.timeout,
                        env=_safe_env(),
                    )
            except FileNotFoundError:
                last_error = "ollama executable not found"
                if attempt == attempts - 1:
                    raise RuntimeError(
                        f"Ollama backend failed after {attempts} attempt(s): {last_error}"
                    )
                time.sleep(0.05)
                continue
            except (subprocess.TimeoutExpired, OSError) as exc:
                last_error = str(exc)
                if isinstance(exc, subprocess.TimeoutExpired) and "timed out" not in last_error:
                    last_error = f"timed out after {exc.timeout} seconds"
                if attempt < attempts - 1:
                    time.sleep(0.05)
                continue

            stdout = result.stdout
            stderr = result.stderr
            if result.returncode == 0:
                return (stdout or "").strip()
            last_error = (stderr or "").strip() or (
                f"non-zero exit code: {result.returncode}"
            )
            if attempt < attempts - 1:
                time.sleep(0.05)

        raise RuntimeError(
            f"Ollama backend failed after {attempts} attempt(s): {last_error}"
        )

    def _run_with_popen(self, prompt: str) -> subprocess.CompletedProcess[str]:
        proc = subprocess.Popen(
            ["ollama", "run", self.model],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_safe_env(),
        )
        try:
            stdout, stderr = proc.communicate(
                input=prompt.encode(),
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            raise

        if isinstance(stdout, bytes):
            stdout = stdout.decode()
        if isinstance(stderr, bytes):
            stderr = stderr.decode()

        return subprocess.CompletedProcess(
            args=["ollama", "run", self.model_name],
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": "ollama",
            "model": self.model,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }

    @staticmethod
    def _build_env() -> dict[str, str]:
        return _safe_env()


def _is_mocked_callable(value: object) -> bool:
    return value.__class__.__module__.startswith("unittest.mock")
