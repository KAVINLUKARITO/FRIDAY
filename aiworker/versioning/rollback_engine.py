"""RollbackEngine — detects score regressions and rolls back safely.

Safety properties:
- Never deletes nodes from the graph (append-only)
- Rollback = move head pointer to last known-good node
- Regression threshold is configurable, not hardcoded
- All results are frozen RollbackResult dataclasses
- No filesystem writes, no subprocess calls
"""
from __future__ import annotations

from typing import Optional

from aiworker.versioning.models import RollbackResult, VersionNode
from aiworker.versioning.version_graph import VersionGraph


class RollbackEngine:
    """Detects regressions and restores the graph head to a safe state.

    Args:
        graph: The :class:`VersionGraph` instance to operate on.
        min_score_delta: How much a score must drop to be a regression.
            e.g. -0.1 means "flag if score drops by more than 10%".
            Must be <= 0.
    """

    def __init__(
        self,
        graph: VersionGraph,
        min_score_delta: float = -0.1,
    ) -> None:
        if min_score_delta > 0:
            raise ValueError(
                f"min_score_delta must be <= 0 (represents a drop), "
                f"got: {min_score_delta}"
            )
        self._graph = graph
        self._min_score_delta = min_score_delta

    def detect_regression(self, new_score: float) -> bool:
        """Return True if new_score represents a regression from current head.

        Args:
            new_score: The score just achieved.

        Returns:
            True if score dropped beyond the threshold.
        """
        current = self._graph.get_latest()
        delta = new_score - current.score
        return round(delta, 10) < self._min_score_delta

    def rollback_to_last_good(
        self,
        from_snapshot_id: Optional[str] = None,
    ) -> RollbackResult:
        """Walk ancestors from the current head to find the last good node.

        "Last good" is defined as the ancestor with the highest score that
        is strictly better than the current head.

        If no better ancestor is found, returns a failed RollbackResult.

        Args:
            from_snapshot_id: Start the walk from this node instead of head.
                              Defaults to current head.

        Returns:
            A frozen :class:`RollbackResult`.
        """
        start_id = from_snapshot_id or self._graph.get_latest().snapshot_id
        start_node = self._graph.get_node(start_id)

        if start_node is None:
            return RollbackResult(
                success=False,
                rolled_back_to=None,
                from_snapshot=start_id,
                reason=f"Start node '{start_id}' not found in graph",
                score_recovered=0.0,
            )

        # Walk ancestors to find the best-scoring one
        ancestors = self._graph.get_ancestors(start_id)
        # Skip the start node itself (index 0)
        candidates = ancestors[1:]

        if not candidates:
            return RollbackResult(
                success=False,
                rolled_back_to=None,
                from_snapshot=start_id,
                reason="No ancestors to roll back to (already at root)",
                score_recovered=0.0,
            )

        # Find ancestor with the highest score
        best = max(candidates, key=lambda n: n.score)

        if best.score <= start_node.score:
            return RollbackResult(
                success=False,
                rolled_back_to=None,
                from_snapshot=start_id,
                reason=(
                    f"No ancestor has a better score than current "
                    f"({start_node.score:.4f})"
                ),
                score_recovered=0.0,
            )

        # Apply rollback: move graph head to best ancestor
        self._graph.set_head(best.snapshot_id)

        return RollbackResult(
            success=True,
            rolled_back_to=best.snapshot_id,
            from_snapshot=start_id,
            reason=(
                f"Regression detected: score dropped from "
                f"{best.score:.4f} to {start_node.score:.4f}. "
                f"Rolled back to node '{best.snapshot_id}'."
            ),
            score_recovered=best.score,
        )

    def rollback_to_node(self, snapshot_id: str) -> RollbackResult:
        """Roll back to a specific named snapshot.

        Args:
            snapshot_id: The exact node to restore head to.

        Returns:
            A frozen :class:`RollbackResult`.
        """
        target = self._graph.get_node(snapshot_id)
        if target is None:
            return RollbackResult(
                success=False,
                rolled_back_to=None,
                from_snapshot=self._graph.get_latest().snapshot_id,
                reason=f"Target node '{snapshot_id}' not found",
                score_recovered=0.0,
            )

        from_id = self._graph.get_latest().snapshot_id
        self._graph.set_head(snapshot_id)

        return RollbackResult(
            success=True,
            rolled_back_to=snapshot_id,
            from_snapshot=from_id,
            reason=f"Explicit rollback to '{snapshot_id}'.",
            score_recovered=target.score,
        )

    @property
    def min_score_delta(self) -> float:
        return self._min_score_delta
