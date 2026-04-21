from __future__ import annotations

import threading
import time
from typing import Any

from config import cfg
from executor import Executor
from observability.logger import logger

from agents.queue import TaskQueue
from agents.result_store import ResultStore


class ExecutorService:
    POLL_INTERVAL = float(cfg.get("executor_poll_interval", 1))
    MAX_WORKERS = int(cfg.get("executor_workers", 2))

    def run_worker(self, worker_id: int) -> None:
        logger.log("EXECUTOR_SVC", "WORKER_START", {"id": worker_id})
        queue = TaskQueue()
        result_store = ResultStore()
        executor = Executor()
        while True:
            task_payload: dict[str, Any] | None = None
            try:
                task_payload = queue.pop(kind="execute")
                if task_payload:
                    logger.log("EXECUTOR_SVC", "TASK_START", {"worker": worker_id, "task_id": task_payload["task_id"]})
                    result = executor.run(str(task_payload["task"]))
                    if not isinstance(result, dict):
                        result = {"success": bool(getattr(result, "success", False)), "output": getattr(result, "output", None)}
                    result["task_id"] = task_payload["task_id"]
                    result["parent_run_id"] = task_payload.get("parent_run_id")
                    result_store.write(str(task_payload["task_id"]), result)
                    requeue_count = int(task_payload.get("requeue_count", 0))
                    if not result.get("goal_achieved") and requeue_count < 3:
                        queue.complete(str(task_payload["task_id"]), result)
                        queue.push(
                            str(task_payload["task"]),
                            priority=8,
                            parent_run_id=str(task_payload["task_id"]),
                            requeue_count=requeue_count + 1,
                            kind="execute",
                        )
                        logger.log("EXECUTOR_SVC", "REQUEUED", task_payload["task_id"])
                    elif not result.get("goal_achieved") and requeue_count >= 3:
                        queue.fail(str(task_payload["task_id"]), "requeue limit reached")
                    else:
                        queue.complete(str(task_payload["task_id"]), result)
                else:
                    time.sleep(self.POLL_INTERVAL)
            except Exception as exc:
                if task_payload:
                    queue.fail(str(task_payload["task_id"]), str(exc))
                logger.log("EXECUTOR_SVC", "WORKER_ERROR", {"worker": worker_id, "error": str(exc)})
                time.sleep(self.POLL_INTERVAL)

    def run(self) -> None:
        threads = [
            threading.Thread(target=self.run_worker, args=(index,), daemon=True)
            for index in range(self.MAX_WORKERS)
        ]
        for thread in threads:
            thread.start()
        logger.log("EXECUTOR_SVC", "START", {"workers": self.MAX_WORKERS})
        for thread in threads:
            thread.join()


if __name__ == "__main__":
    ExecutorService().run()
