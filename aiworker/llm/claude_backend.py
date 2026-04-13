import json
import os
from typing import Optional


class ClaudeBackend:
    """
    Deterministic Claude backend for strict JSON patch generation.

    - No streaming
    - Enforces max_tokens
    - No global mutable state
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 2000,
    ) -> None:
        try:
            import anthropic
        except Exception as exc:
            raise RuntimeError("anthropic package is not installed") from exc

        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        self.model = model
        self.max_tokens = max_tokens
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def generate(self, prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        return response.content[0].text.strip()
