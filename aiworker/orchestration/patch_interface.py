"""Patch generator protocol for injected LLM-backed generation."""

from __future__ import annotations

from typing import Optional, Protocol, Sequence

from aiworker.orchestration.architecture_models import AtomicTask


class PatchGenerator(Protocol):
    """Interface for patch generation with no model implementation."""

    def generate(
        self,
        plan: AtomicTask,
        goal: str,
        allowed_files: Sequence[str],
        seed: int,
    ) -> Optional[str]:
        """Return JSON payload text or ``None`` when no patch is generated."""


__all__ = ["PatchGenerator"]
