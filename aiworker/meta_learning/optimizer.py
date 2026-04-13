"""Compatibility exports for the renamed meta-learning optimizer module."""

from aiworker.meta_learning.meta_optimizer import (
    MetaLearningOptimizer,
    StrategyRecommendation,
    create_meta_optimizer,
    meta_optimizer,
)

__all__ = [
    "MetaLearningOptimizer",
    "StrategyRecommendation",
    "create_meta_optimizer",
    "meta_optimizer",
]
