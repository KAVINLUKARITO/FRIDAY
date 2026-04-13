"""Data models for the Version Graph — Phase 6.

All models are frozen dataclasses.
No mutable shared state. No filesystem access in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class VersionNode:
    """A single node in the version DAG.

    Attributes:
        snapshot_id: Unique identifier for this version snapshot.
        parent_id: ID of the parent node, or None for the root.
        timestamp: ISO-8601 UTC timestamp of creation.
        score: Confidence/quality score at this version [0.0, 1.0].
        metadata: Arbitrary JSON-serialisable context (goal, files, etc.).
    """
    snapshot_id: str
    parent_id: Optional[str]
    timestamp: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "parent_id": self.parent_id,
            "timestamp": self.timestamp,
            "score": self.score,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RollbackResult:
    """Result of a rollback operation."""
    success: bool
    rolled_back_to: Optional[str]   # snapshot_id
    from_snapshot: Optional[str]    # snapshot_id that was abandoned
    reason: str
    score_recovered: float

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "rolled_back_to": self.rolled_back_to,
            "from_snapshot": self.from_snapshot,
            "reason": self.reason,
            "score_recovered": self.score_recovered,
        }
