from __future__ import annotations

import sys

from aiworker.evolution import Prompt_tuner as _prompt_tuner

PromptTuner = _prompt_tuner.PromptTuner
PromptVariant = _prompt_tuner.PromptVariant
sys.modules[__name__ + ".prompt_tuner"] = _prompt_tuner

__all__ = ["PromptTuner", "PromptVariant"]
