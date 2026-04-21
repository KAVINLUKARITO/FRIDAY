from __future__ import annotations

import time

from config import cfg
from friday.planner import Planner
from memory.store import read_memory
from observability.logger import logger

from agents.queue import TaskQueue


class PlannerService:
    POLL_INTERVAL = float(cfg.get("planner_poll_interval", 2))

    def run(self) -> None:
        logger.log("PLANNER_SVC", "START", {})
        queue = TaskQueue()
        planner = Planner()
        while True:
            try:
                task_payload = queue.pop(kind="plan")
                if task_payload:
                    logger.log("PLANNER_SVC", "TASK_RECEIVED", task_payload["task_id"])
                    task_text = str(task_payload.get("task", ""))
                    memory_ctx = read_memory(task_text)
                    steps = planner.plan(task_text, memory_ctx)
                    if not steps:
                        steps = [{"step": 1, "task": task_text}]
                    for step in steps:
                        queue.push(
                            task=str(step.get("task", task_text)),
                            priority=int(step.get("step", 5)),
                            parent_run_id=str(task_payload["task_id"]),
                            requeue_count=int(task_payload.get("requeue_count", 0)),
                            kind="execute",
                        )
                    queue.complete(
                        str(task_payload["task_id"]),
                        {"planned_steps": len(steps), "task": task_text},
                    )
                    logger.log("PLANNER_SVC", "PLAN_DISPATCHED", {"steps": len(steps), "parent": task_payload["task_id"]})
                else:
                    time.sleep(self.POLL_INTERVAL)
            except Exception as exc:
                logger.log("PLANNER_SVC", "ERROR", str(exc))
                time.sleep(self.POLL_INTERVAL)


if __name__ == "__main__":
    PlannerService().run()
