from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ResultStore:
    STORE_PATH = Path("agents/.results")

    def __init__(self) -> None:
        self.STORE_PATH.mkdir(parents=True, exist_ok=True)

    def write(self, task_id: str, result: dict[str, Any]) -> None:
        path = self.STORE_PATH / f"{task_id}.json"
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        tmp_path.replace(path)

    def read(self, task_id: str) -> dict[str, Any] | None:
        path = self.STORE_PATH / f"{task_id}.json"
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def list_results(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for path in sorted(self.STORE_PATH.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            parsed = self.read(path.stem)
            if parsed is not None:
                results.append(parsed)
        return results
