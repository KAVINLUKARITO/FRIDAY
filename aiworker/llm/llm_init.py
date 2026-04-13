"""LLM integration adapters for the autonomous evolution pipeline.

Public API:
    DeepSeekAdapter — PatchGenerator via local Ollama subprocess.
    RepairAdapter — strict JSON repair pipeline adapter.
    DeepSeekResponse — validated response model.
    GenerationBackend — injectable backend protocol.
    StubBackend — deterministic testing backend.
"""

from aiworker.llm.deepseek_adapter import (
    DeepSeekAdapter,
)
from aiworker.llm.repair_adapter import (
    DeepSeekResponse,
    GenerationBackend,
    RepairAdapter,
    StubBackend,
)

__all__ = [
    "DeepSeekAdapter",
    "DeepSeekResponse",
    "GenerationBackend",
    "RepairAdapter",
    "StubBackend",
]
