from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import cfg
from observability.logger import logger


MEMORY_PATH = Path("memory/agent_memory.json")
REFLECTIONS_PATH = Path("memory/reflections.json")
GOALS_PATH = Path("memory/goals.json")
LOCK_PATH = Path("memory/.write.lock")
MAX_MEMORY_RECORDS = int(cfg.get("memory_max_records", 500))


def _log(event: str, payload: str) -> None:
    logger.log("MEMORY", event, payload)


def _load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed
    except Exception:
        return default


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    parsed = _load_json(path, [])
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _load_records(path: Path = MEMORY_PATH) -> list[dict[str, Any]]:
    return _load_json_list(path)


def _acquire_lock(lock_path: str, timeout: int = 5) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.05)
    return False


def _release_lock(lock_path: str) -> None:
    try:
        os.remove(lock_path)
    except Exception:
        pass


def _atomic_write(path: Path, payload: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception as exc:
        logger.log("FALLBACK", "reason", str(exc))


def write_memory(record: dict[str, Any]) -> None:
    lock_acquired = _acquire_lock(str(LOCK_PATH))
    if not lock_acquired:
        logger.log("MEMORY", "LOCK_WARNING", "memory/.write.lock not acquired within 5s")
    try:
        validated = {
            "task": str(record["task"]),
            "tool": str(record["tool"]),
            "success": bool(record["success"]),
            "score": float(record["score"]),
            "timestamp": str(record["timestamp"]),
        }
        payload = _load_records(MEMORY_PATH)
        payload.append(validated)
        payload = payload[-MAX_MEMORY_RECORDS:]
        _atomic_write(MEMORY_PATH, payload)
        _log(
            "MEMORY_WRITE",
            f"task={validated['task']} tool={validated['tool']} success={validated['success']}",
        )
    except Exception as exc:
        logger.log("FALLBACK", "reason", str(exc))
    finally:
        if lock_acquired:
            _release_lock(str(LOCK_PATH))


def read_memory(task: str) -> dict[str, Any]:
    try:
        lowered_task = task.casefold()
        matches = [
            item
            for item in _load_json_list(MEMORY_PATH)
            if isinstance(item.get("task"), str) and lowered_task in item["task"].casefold()
        ]
        if not matches:
            return {"best_tools": [], "failed_tools": []}
        successful = sorted(
            [
                item
                for item in matches
                if item.get("success") is True and isinstance(item.get("tool"), str)
            ],
            key=lambda item: float(item.get("score", 0.0)),
            reverse=True,
        )
        failed_tools: list[str] = []
        for item in matches:
            tool = item.get("tool")
            if item.get("success") is False and isinstance(tool, str) and tool not in failed_tools:
                failed_tools.append(tool)
        return {
            "best_tools": [item["tool"] for item in successful[:3]],
            "failed_tools": failed_tools[:3],
        }
    except Exception:
        return {"best_tools": [], "failed_tools": []}


def write_reflection(reflection: dict[str, Any]) -> None:
    lock_acquired = _acquire_lock(str(LOCK_PATH))
    if not lock_acquired:
        logger.log("MEMORY", "LOCK_WARNING", "memory/.write.lock not acquired within 5s")
    try:
        validated = {
            "task": str(reflection["task"]),
            "failures": list(reflection["failures"]),
            "success_pattern": str(reflection["success_pattern"]),
            "improvement": str(reflection["improvement"]),
        }
        payload = _load_json_list(REFLECTIONS_PATH)
        payload.append(validated)
        _atomic_write(REFLECTIONS_PATH, payload)
        _log("REFLECTION_WRITE", f"task={validated['task']}")
    except Exception as exc:
        logger.log("FALLBACK", "reason", str(exc))
    finally:
        if lock_acquired:
            _release_lock(str(LOCK_PATH))


def get_tool_scores() -> dict[str, float]:
    records = _load_records(MEMORY_PATH)
    scores: dict[str, float] = {}
    counts: dict[str, int] = {}
    for record in records:
        tool = str(record.get("tool", "")).strip()
        if not tool:
            continue
        try:
            score = float(record.get("score", 0.0))
        except Exception:
            score = 0.0
        scores[tool] = scores.get(tool, 0.0) + score
        counts[tool] = counts.get(tool, 0) + 1
    return {tool: round(scores[tool] / counts[tool], 3) for tool in scores if counts.get(tool, 0)}


def write_goal_progress(goal: str, sub_goals: list[str], results: list[dict[str, Any]]) -> None:
    lock_acquired = _acquire_lock(str(LOCK_PATH))
    if not lock_acquired:
        logger.log("MEMORY", "LOCK_WARNING", "memory/.write.lock not acquired within 5s")
    try:
        record = {
            "goal": goal,
            "sub_goals": [str(item) for item in sub_goals],
            "results": [
                {
                    "sub_goal": str(item.get("sub_goal", "")),
                    "achieved": bool((item.get("result") or {}).get("goal_achieved", False)),
                    "steps": int((item.get("result") or {}).get("steps_completed", 0)),
                    "run_id": str((item.get("result") or {}).get("run_id", "")),
                }
                for item in results
                if isinstance(item, dict)
            ],
            "total_achieved": sum(1 for item in results if bool((item.get("result") or {}).get("goal_achieved", False))),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        payload = _load_json_list(GOALS_PATH)
        payload.append(record)
        _atomic_write(GOALS_PATH, payload)
        _log("GOAL_WRITE", goal)
    except Exception as exc:
        logger.log("FALLBACK", "reason", str(exc))
    finally:
        if lock_acquired:
            _release_lock(str(LOCK_PATH))
