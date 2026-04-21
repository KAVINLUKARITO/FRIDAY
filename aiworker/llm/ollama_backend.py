"""Ollama prompt backend using the local HTTP API."""

from __future__ import annotations

import requests


class OllamaBackend:
    """Prompt-in, text-out backend around the local Ollama HTTP API."""

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
        return self.model.strip()

    def generate(self, prompt: str) -> str:
        try:
            url = "http://127.0.0.1:11434/api/generate"

            payload = {
                "model": self.model_name.strip(),
                "prompt": prompt,
                "stream": False,
            }

            headers = {
                "Content-Type": "application/json",
            }

            print(f"[OLLAMA REQUEST] model={self.model_name}")

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=300,
            )

            print(f"[OLLAMA DEBUG] status={response.status_code}")
            print(f"[OLLAMA DEBUG] body={response.text[:300]}")

            response.raise_for_status()

            data = response.json()

            return data.get("response", "").strip()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama HTTP request failed: {e}")

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": "ollama",
            "model": self.model,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }
