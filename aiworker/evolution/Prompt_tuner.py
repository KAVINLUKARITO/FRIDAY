from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from aiworker.config import AIWorkerConfig


@dataclass
class PromptVariant:
    name: str
    template: str
    usage_count: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    avg_output_quality: float = 0.0
    avg_duration_seconds: float = 0.0
    created_at: float = field(default_factory=time.time)
    is_active: bool = False
    parent_variant: str | None = None

    def record_usage(self, success: bool, quality: float, duration: float) -> None:
        self.usage_count += 1
        if success:
            self.success_count += 1
        self.success_rate = self.success_count / self.usage_count
        self.avg_output_quality = quality if self.usage_count == 1 else (
            (self.avg_output_quality * (self.usage_count - 1) + quality) / self.usage_count
        )
        self.avg_duration_seconds = duration if self.usage_count == 1 else (
            (self.avg_duration_seconds * (self.usage_count - 1) + duration) / self.usage_count
        )


class PromptTuner:
    DEFAULT_PROMPTS = {
        "code_generation": "Generate correct Python code for: {task_description}",
        "research": "Research: {query}",
        "planning": "Plan: {goal}",
        "validation": "Validate: {code}",
    }

    def __init__(self, config: AIWorkerConfig | None = None) -> None:
        self.config = config or AIWorkerConfig.from_env()
        self.base_path = Path(self.config.base_path)
        self.min_samples = 10
        self._variants: dict[str, list[PromptVariant]] = {}

    def _ensure_variant(self, prompt_type: str) -> PromptVariant:
        variants = self._variants.setdefault(prompt_type, [])
        if variants:
            return next((variant for variant in variants if variant.is_active), variants[0])
        variant = PromptVariant(
            name=f"{prompt_type}_default",
            template=self.get_template(prompt_type),
            is_active=True,
        )
        variants.append(variant)
        return variant

    def get_template(self, prompt_type: str) -> str:
        return self.DEFAULT_PROMPTS.get(prompt_type, "{input}")

    def record_outcome(self, prompt_type: str, success: bool, quality: float, duration: float) -> PromptVariant:
        variant = self._ensure_variant(prompt_type)
        variant.record_usage(success=success, quality=quality, duration=duration)
        return variant

    def get_variant_stats(self, prompt_type: str) -> list[dict[str, object]]:
        self._ensure_variant(prompt_type)
        return [
            {
                "name": variant.name,
                "template": variant.template,
                "usage_count": variant.usage_count,
                "success_rate": variant.success_rate,
                "avg_output_quality": variant.avg_output_quality,
                "avg_duration_seconds": variant.avg_duration_seconds,
                "is_active": variant.is_active,
            }
            for variant in self._variants[prompt_type]
        ]

    def evolve(self, prompt_type: str) -> PromptVariant | None:
        active = self._ensure_variant(prompt_type)
        if active.usage_count < self.min_samples:
            return None
        new_variant = PromptVariant(
            name=f"{prompt_type}_variant_{len(self._variants[prompt_type]) + 1}",
            template=f"{active.template}\nBe precise and verify edge cases.",
            is_active=False,
            parent_variant=active.name,
        )
        self._variants[prompt_type].append(new_variant)
        return new_variant
