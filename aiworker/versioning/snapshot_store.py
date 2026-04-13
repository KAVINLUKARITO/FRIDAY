"""SnapshotStore — persists patch snapshots for each version node.

Properties:
- SQLite-backed, single persistent connection for :memory:
- All SQL parameterised — no string interpolation
- Append-only: snapshots are never deleted
- Returns None for missing snapshot IDs, never raises on lookup
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SnapshotStore:
    """Persists and retrieves patch content linked to version nodes.

    Args:
        path: SQLite file path. Use ":memory:" for in-process storage.
    """

    def __init__(self, path: str = ":memory:") -> None:
        self._path = path
        self._conn: Optional[sqlite3.Connection] = None
        if path == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.row_factory = sqlite3.Row

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        cur = self._get_conn().execute(sql, params)
        self._get_conn().commit()
        return cur

    def _fetchone(self, sql: str, params: tuple = ()):
        return self._get_conn().execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple = ()) -> list:
        return self._get_conn().execute(sql, params).fetchall()

    def initialise(self) -> None:
        """Create tables if they do not exist (idempotent)."""
        self._execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id  TEXT PRIMARY KEY,
                node_id      TEXT NOT NULL,
                patch_diff   TEXT NOT NULL,
                goal         TEXT NOT NULL,
                files_changed TEXT NOT NULL DEFAULT '[]',
                created_at   TEXT NOT NULL,
                metadata     TEXT NOT NULL DEFAULT '{}'
            )
        """)

    def save(
        self,
        node_id: str,
        patch_diff: str,
        goal: str,
        files_changed: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist a patch snapshot for a version node.

        Args:
            node_id: The VersionNode snapshot_id this snapshot belongs to.
            patch_diff: The unified diff string.
            goal: The goal that produced this patch.
            files_changed: List of files modified by the patch.
            metadata: Optional extra context.

        Returns:
            The new snapshot_id (UUID).
        """
        snapshot_id = str(uuid.uuid4())
        self._execute(
            "INSERT INTO snapshots "
            "(snapshot_id, node_id, patch_diff, goal, files_changed, created_at, metadata) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                snapshot_id,
                node_id,
                patch_diff,
                goal,
                json.dumps(files_changed or []),
                _utcnow(),
                json.dumps(metadata or {}),
            ),
        )
        return snapshot_id

    def get_by_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the snapshot for a given node_id.

        Returns:
            Dict with snapshot fields, or None if not found.
        """
        row = self._fetchone(
            "SELECT * FROM snapshots WHERE node_id = ? ORDER BY created_at DESC LIMIT 1",
            (node_id,),
        )
        if row is None:
            return None
        return self._row_to_dict(row)

    def get_by_snapshot_id(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a snapshot by its own ID."""
        row = self._fetchone(
            "SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
        )
        return self._row_to_dict(row) if row else None

    def list_by_node_ids(self, node_ids: List[str]) -> List[Dict[str, Any]]:
        """Retrieve all snapshots for a list of node IDs."""
        if not node_ids:
            return []
        placeholders = ",".join("?" * len(node_ids))
        rows = self._fetchall(
            f"SELECT * FROM snapshots WHERE node_id IN ({placeholders}) "
            "ORDER BY created_at ASC",
            tuple(node_ids),
        )
        return [self._row_to_dict(r) for r in rows]

    def count(self) -> int:
        """Return total number of stored snapshots."""
        row = self._fetchone("SELECT COUNT(*) as n FROM snapshots")
        return int(row["n"]) if row else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "snapshot_id": row["snapshot_id"],
            "node_id": row["node_id"],
            "patch_diff": row["patch_diff"],
            "goal": row["goal"],
            "files_changed": json.loads(row["files_changed"]),
            "created_at": row["created_at"],
            "metadata": json.loads(row["metadata"]),
        }
