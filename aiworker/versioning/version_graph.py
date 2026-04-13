"""VersionGraph — directed acyclic graph of version snapshots.

Properties:
- Append-only: nodes are never deleted, only superseded
- Deterministic: same operations produce same graph state
- No mutable shared state between instances
- Thread-safe reads (no writes during iteration)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from aiworker.versioning.models import VersionNode


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class VersionGraph:
    """DAG of VersionNode objects tracking system evolution.

    The graph has exactly one root node (parent_id=None).
    Every subsequent node has a parent_id pointing to an existing node.

    Args:
        initial_score: Score to assign the root node.
    """

    def __init__(self, initial_score: float = 0.0) -> None:
        root = VersionNode(
            snapshot_id=_new_id(),
            parent_id=None,
            timestamp=_utcnow(),
            score=max(0.0, min(1.0, initial_score)),
            metadata={"label": "root"},
        )
        self._nodes: Dict[str, VersionNode] = {root.snapshot_id: root}
        self._head: str = root.snapshot_id  # current latest node

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_node(
        self,
        score: float,
        parent_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> VersionNode:
        """Add a new node to the graph.

        Args:
            score: Quality/confidence score [0.0, 1.0].
            parent_id: Parent snapshot ID. Defaults to current head.
            metadata: Optional context dictionary.

        Returns:
            The newly created :class:`VersionNode`.

        Raises:
            ValueError: If parent_id is provided but does not exist.
        """
        resolved_parent = parent_id if parent_id is not None else self._head

        if resolved_parent not in self._nodes:
            raise ValueError(
                f"Parent node '{resolved_parent}' does not exist in the graph."
            )

        node = VersionNode(
            snapshot_id=_new_id(),
            parent_id=resolved_parent,
            timestamp=_utcnow(),
            score=max(0.0, min(1.0, float(score))),
            metadata=dict(metadata) if metadata else {},
        )
        self._nodes[node.snapshot_id] = node
        self._head = node.snapshot_id
        return node

    def set_head(self, snapshot_id: str) -> None:
        """Manually move the head pointer (used by rollback).

        Raises:
            ValueError: If snapshot_id does not exist.
        """
        if snapshot_id not in self._nodes:
            raise ValueError(f"Snapshot '{snapshot_id}' not in graph.")
        self._head = snapshot_id

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_node(self, snapshot_id: str) -> Optional[VersionNode]:
        """Return the node with the given ID, or None."""
        return self._nodes.get(snapshot_id)

    def get_latest(self) -> VersionNode:
        """Return the current head node."""
        return self._nodes[self._head]

    def get_parent(self, snapshot_id: str) -> Optional[VersionNode]:
        """Return the parent of the given node, or None for root."""
        node = self._nodes.get(snapshot_id)
        if node is None or node.parent_id is None:
            return None
        return self._nodes.get(node.parent_id)

    def get_ancestors(self, snapshot_id: str) -> List[VersionNode]:
        """Return the chain of ancestors from snapshot_id to root (inclusive).

        The list is ordered: [snapshot_id node, parent, grandparent, ..., root].
        """
        chain: List[VersionNode] = []
        current_id: Optional[str] = snapshot_id
        visited = set()

        while current_id is not None:
            if current_id in visited:
                break  # cycle guard
            visited.add(current_id)
            node = self._nodes.get(current_id)
            if node is None:
                break
            chain.append(node)
            current_id = node.parent_id

        return chain

    def get_root(self) -> VersionNode:
        """Return the root node (the only node with parent_id=None)."""
        for node in self._nodes.values():
            if node.parent_id is None:
                return node
        raise RuntimeError("Graph has no root node — invariant violated.")

    def all_nodes(self) -> List[VersionNode]:
        """Return all nodes ordered by timestamp ascending."""
        return sorted(self._nodes.values(), key=lambda n: n.timestamp)

    def size(self) -> int:
        """Return total number of nodes in the graph."""
        return len(self._nodes)

    def to_dict(self) -> dict:
        return {
            "head": self._head,
            "size": self.size(),
            "nodes": [n.to_dict() for n in self.all_nodes()],
        }
