"""JSONL persistence for agent state and short-term history."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Literal

from aiworker.models import MemoryRecord

logger = logging.getLogger(__name__)


class MemoryStore:
    """Append-only JSONL memory store with defensive file I/O handling."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        task_id: str,
        role: Literal["task", "plan", "tool", "agent"],
        content: dict,
    ) -> MemoryRecord:
        record = MemoryRecord(task_id=task_id, role=role, content=content)
        line = record.model_dump_json()
        with self._lock:
            try:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                logger.exception("failed to persist memory record")
                raise
        return record

    def recent(self, limit: int = 20) -> list[MemoryRecord]:
        with self._lock:
            if not self.path.exists():
                return []
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
            except OSError:
                logger.exception("failed to read memory records")
                return []

        records: list[MemoryRecord] = []
        for line in lines:
            try:
                records.append(MemoryRecord.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                logger.warning("skipping invalid memory record")
        return records
