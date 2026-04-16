"""Ollama prompt backend with retry logic."""

from __future__ import annotations
import os
import shutil
import subprocess
import time
import requests


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
        import requests

        try:
            response = requests.post(
                "http://127.0.0.1:11434/api/generate",
                json={
                    "model": self.model_name,
                   "prompt": prompt,
                   "stream": False
                    },
                timeout=300
            )

            response.raise_for_status()

            data = response.json()
            return data.get("response", "").strip()

        except Exception as e:
            raise RuntimeError(f"Ollama HTTP backend failed: {e}")

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
