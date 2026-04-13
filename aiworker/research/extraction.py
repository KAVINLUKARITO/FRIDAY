import json
from typing import Protocol

from aiworker.research.models import ExtractedKnowledge, RawDocument

_REQUIRED_KEYS: frozenset[str] = frozenset(
    ("summary", "key_concepts", "code_snippets", "claims", "risks")
)
_LIST_KEYS: frozenset[str] = frozenset(
    ("key_concepts", "code_snippets", "claims", "risks")
)


class GenerationBackend(Protocol):
    def generate(self, prompt: str) -> str: ...


class StubBackend:

    def __init__(self, response: str) -> None:
        self._response: str = response
        self.call_count: int = 0

    def generate(self, prompt: str) -> str:
        self.call_count += 1
        return self._response


class ExtractionEngine:

    def __init__(self, backend: GenerationBackend) -> None:
        self._backend: GenerationBackend = backend

    def extract(self, document: RawDocument) -> ExtractedKnowledge:
        prompt: str = _build_prompt(document)
        raw: str = self._backend.generate(prompt)
        validated: dict[str, object] = _validate_response(raw)
        return ExtractedKnowledge(
            summary=str(validated["summary"]),
            key_concepts=tuple(str(s) for s in validated["key_concepts"]),  # type: ignore[union-attr]
            code_snippets=tuple(str(s) for s in validated["code_snippets"]),  # type: ignore[union-attr]
            claims=tuple(str(s) for s in validated["claims"]),  # type: ignore[union-attr]
            risks=tuple(str(s) for s in validated["risks"]),  # type: ignore[union-attr]
            source_domain=document.domain,
        )


def _build_prompt(document: RawDocument) -> str:
    return (
        "Return STRICT JSON ONLY. "
        "Do not include markdown, code fences, or any commentary.\n\n"
        "Required JSON schema:\n"
        "{\n"
        '  "summary": "<non-empty string>",\n'
        '  "key_concepts": ["<string>", ...],\n'
        '  "code_snippets": ["<string>", ...],\n'
        '  "claims": ["<string>", ...],\n'
        '  "risks": ["<string>", ...]\n'
        "}\n\n"
        "Rules:\n"
        "- summary must be non-empty.\n"
        "- key_concepts must contain at least 1 item.\n"
        "- No extra keys.\n"
        "- No empty strings in lists.\n\n"
        "Document content:\n"
        f"{document.content}"
    )


def _validate_response(raw: str) -> dict[str, object]:
    if not raw or not raw.strip():
        raise ValueError("Response is empty")

    stripped: str = raw.strip()

    if "```" in stripped:
        raise ValueError("Response contains markdown code fences")

    try:
        parsed: object = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Response is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Response must be a JSON object, got {type(parsed).__name__}"
        )

    actual_keys: set[str] = set(parsed.keys())

    missing: frozenset[str] = _REQUIRED_KEYS - actual_keys
    if missing:
        raise ValueError(f"Missing required keys: {sorted(missing)}")

    extra: set[str] = actual_keys - _REQUIRED_KEYS
    if extra:
        raise ValueError(f"Extra keys not allowed: {sorted(extra)}")

    summary: object = parsed["summary"]
    if not isinstance(summary, str):
        raise ValueError(
            f"summary must be a string, got {type(summary).__name__}"
        )
    if not summary.strip():
        raise ValueError("summary must be non-empty")

    for key in _LIST_KEYS:
        value: object = parsed[key]
        if not isinstance(value, list):
            raise ValueError(
                f"{key} must be a list, got {type(value).__name__}"
            )
        for i, item in enumerate(value):
            if not isinstance(item, str):
                raise ValueError(
                    f"{key}[{i}] must be a string, got {type(item).__name__}"
                )
            if not item.strip():
                raise ValueError(f"{key}[{i}] must not be an empty string")

    concepts: list[object] = parsed["key_concepts"]
    if len(concepts) < 1:
        raise ValueError("key_concepts must contain at least 1 item")

    return parsed  # type: ignore[return-value]
