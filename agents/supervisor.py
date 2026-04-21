from __future__ import annotations

import importlib
import threading
import time
from typing import Any

from config import cfg
from observability.logger import logger

from agents.queue import TaskQueue


class Supervisor:
    SERVICES = [
        {"name": "planner", "module": "agents.planner_service", "class": "PlannerService"},
        {"name": "executor", "module": "agents.executor_service", "class": "ExecutorService"},
    ]
    RESTART_DELAY = float(cfg.get("supervisor_restart_delay", 3))

    def _start_service(self, svc: dict[str, str]) -> threading.Thread:
        def target() -> None:
            while True:
                try:
                    logger.log("SUPERVISOR", "START", svc["name"])
                    module = importlib.import_module(svc["module"])
                    cls = getattr(module, svc["class"])
                    cls().run()
                except Exception as exc:
                    logger.log("SUPERVISOR", "CRASH", {"service": svc["name"], "error": str(exc)})
                    time.sleep(self.RESTART_DELAY)
                    logger.log("SUPERVISOR", "RESTART", svc["name"])

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread

    def health(self) -> dict[str, Any]:
        queue = TaskQueue()
        return {
            "status": "ok",
            "pending": len(queue.list_pending()),
            "processing": len(queue.list_processing()),
            "completed": len(queue.list_completed()),
            "failed": len(queue.list_failed()),
            "services": [service["name"] for service in self.SERVICES],
        }

    def run(self) -> None:
        threads = [self._start_service(service) for service in self.SERVICES]
        logger.log("SUPERVISOR", "ALL_STARTED", {})
        while True:
            time.sleep(30)
            logger.log("SUPERVISOR", "HEALTH", self.health())
            for thread in threads:
                if not thread.is_alive():
                    logger.log("SUPERVISOR", "THREAD_DEAD", {})


if __name__ == "__main__":
    Supervisor().run()
