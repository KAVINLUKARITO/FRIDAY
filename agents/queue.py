from __future__ import annotations

import json
import uuid
from datetime import datetime, UTC
from pathlib import Path
from typing import Any


QUEUE_ROOT = Path("agents/.queue")
PENDING_DIR = QUEUE_ROOT / "pending"
PROCESSING_DIR = QUEUE_ROOT / "processing"
COMPLETED_DIR = QUEUE_ROOT / "completed"
FAILED_DIR = QUEUE_ROOT / "failed"


def _ensure_dirs() -> None:
    for path in (PENDING_DIR, PROCESSING_DIR, COMPLETED_DIR, FAILED_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


class TaskQueue:
    def __init__(self) -> None:
        _ensure_dirs()

    def push(
        self,
        task: str,
        priority: int = 5,
        parent_run_id: str | None = None,
        requeue_count: int = 0,
        kind: str = "plan",
    ) -> str:
        task_id = str(uuid.uuid4())[:12]
        payload = {
            "task_id": task_id,
            "task": task,
            "priority": priority,
            "parent_run_id": parent_run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "pending",
            "requeue_count": requeue_count,
            "kind": kind,
        }
        _atomic_write(PENDING_DIR / f"{task_id}.json", payload)
        return task_id

    def pop(self, kind: str | None = None) -> dict[str, Any] | None:
        files = sorted(
            PENDING_DIR.glob("*.json"),
            key=lambda item: (
                int((_load_json(item, {}) or {}).get("priority", 5)),
                str((_load_json(item, {}) or {}).get("created_at", "")),
            ),
        )
        for path in files:
            try:
                payload = _load_json(path, {})
                if not isinstance(payload, dict) or "task_id" not in payload:
                    continue
                if kind is not None and str(payload.get("kind", "plan")) != kind:
                    continue
                dest = PROCESSING_DIR / path.name
                path.rename(dest)
                payload["status"] = "processing"
                _atomic_write(dest, payload)
                return payload
            except Exception:
                continue
        return None

    def complete(self, task_id: str, result: dict[str, Any]) -> None:
        src = PROCESSING_DIR / f"{task_id}.json"
        payload = _load_json(src, {})
        if not isinstance(payload, dict):
            payload = {"task_id": task_id}
        payload["status"] = "completed"
        payload["completed_at"] = datetime.now(UTC).isoformat()
        payload["result"] = result
        dest = COMPLETED_DIR / f"{task_id}.json"
        _atomic_write(dest, payload)
        try:
            src.unlink()
        except FileNotFoundError:
            pass

    def fail(self, task_id: str, error: str) -> None:
        src = PROCESSING_DIR / f"{task_id}.json"
        payload = _load_json(src, {})
        if not isinstance(payload, dict):
            payload = {"task_id": task_id}
        payload["status"] = "failed"
        payload["failed_at"] = datetime.now(UTC).isoformat()
        payload["error"] = error
        dest = FAILED_DIR / f"{task_id}.json"
        _atomic_write(dest, payload)
        try:
            src.unlink()
        except FileNotFoundError:
            pass

    def status(self, task_id: str) -> str:
        for state, directory in (
            ("pending", PENDING_DIR),
            ("processing", PROCESSING_DIR),
            ("completed", COMPLETED_DIR),
            ("failed", FAILED_DIR),
        ):
            if (directory / f"{task_id}.json").exists():
                return state
        return "not_found"

    def list_pending(self, kind: str | None = None) -> list[dict[str, Any]]:
        payloads = [payload for path in sorted(PENDING_DIR.glob("*.json")) if isinstance((payload := _load_json(path, {})), dict)]
        if kind is None:
            return payloads
        return [payload for payload in payloads if str(payload.get("kind", "plan")) == kind]

    def list_processing(self, kind: str | None = None) -> list[dict[str, Any]]:
        payloads = [payload for path in sorted(PROCESSING_DIR.glob("*.json")) if isinstance((payload := _load_json(path, {})), dict)]
        if kind is None:
            return payloads
        return [payload for payload in payloads if str(payload.get("kind", "plan")) == kind]

    def list_completed(self, kind: str | None = None) -> list[dict[str, Any]]:
        payloads = [payload for path in sorted(COMPLETED_DIR.glob("*.json")) if isinstance((payload := _load_json(path, {})), dict)]
        if kind is None:
            return payloads
        return [payload for payload in payloads if str(payload.get("kind", "plan")) == kind]

    def list_failed(self, kind: str | None = None) -> list[dict[str, Any]]:
        payloads = [payload for path in sorted(FAILED_DIR.glob("*.json")) if isinstance((payload := _load_json(path, {})), dict)]
        if kind is None:
            return payloads
        return [payload for payload in payloads if str(payload.get("kind", "plan")) == kind]
