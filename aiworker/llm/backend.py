"""Abstract base for LLM generation backends.

All backends must implement generate(prompt) -> str.
No network calls, no side effects in this module.
"""
from __future__ import annotations
from abc import ABC, abstractmethod


class GenerationBackend(ABC):
    """Interface contract for all LLM backends."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate a response for the given prompt.

        Args:
            prompt: The input prompt string.

        Returns:
            Raw response string from the model.

        Raises:
            RuntimeError: If generation fails after all retries.
        """
