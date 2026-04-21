from __future__ import annotations

import datetime
import json
import os
import uuid
from typing import Any


class AgentLogger:
    """
    Dual-output logger: stdout (human-readable) + JSONL file sink.
    """

    LOG_FILE = "observability/agent_run.jsonl"

    def __init__(self) -> None:
        os.makedirs("observability", exist_ok=True)
        self._run_id = ""
        self._trace: list[dict[str, Any]] = []

    def log(self, component: str, event: str, payload: Any = None) -> None:
        record = {
            "ts": datetime.datetime.now(datetime.UTC).isoformat(),
            "component": component,
            "event": event,
            "payload": payload,
        }
        payload_str = json.dumps(payload) if payload is not None else ""
        print(f"[AIWORKER][{component}] {event}: {payload_str}")
        try:
            with open(self.LOG_FILE, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except Exception:
            pass

    def begin_run(self, task: str) -> str:
        self._run_id = str(uuid.uuid4())[:8]
        self._trace = []
        self.log("EXECUTOR", "RUN_START", {"run_id": self._run_id, "task": task})
        return self._run_id

    def trace(self, event: str, data: dict[str, Any]) -> None:
        self._trace.append(
            {
                "ts": datetime.datetime.now(datetime.UTC).isoformat(),
                "event": event,
                "data": data,
            }
        )

    def end_run(self, result: dict[str, Any]) -> None:
        os.makedirs("observability/runs", exist_ok=True)
        path = f"observability/runs/{self._run_id}.json"
        payload = {"run_id": self._run_id, "result": result, "trace": self._trace}
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            self.log("EXECUTOR", "RUN_END", {"run_id": self._run_id, "trace_path": path})
        except Exception:
            pass


logger = AgentLogger()
