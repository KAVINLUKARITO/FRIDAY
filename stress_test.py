from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from control import AgentConfig, AgentController
from monitor import Monitor
from supervisor import Supervisor, SupervisorState


@dataclass
class StressTestResult:
    total_cycles: int
    successful_cycles: int
    failed_cycles: int
    infinite_loops_detected: int
    repeated_actions_detected: int
    avg_cycle_time: float
    max_cycle_time: float
    min_cycle_time: float
    failure_log: list[dict[str, Any]] = field(default_factory=list)
    performance_metrics: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def save(self, path: str) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")


class StressTester:
    """Deterministic long-run stability tester."""

    def __init__(
        self,
        agent_controller: AgentController,
        monitor: Monitor,
        supervisor: Supervisor,
    ) -> None:
        self.controller = agent_controller
        self.monitor = monitor
        self.supervisor = supervisor
        self._stop_requested = False

    async def run_stress_test(
        self,
        cycles: int = 1000,
        max_duration_seconds: float | None = None,
        inject_failures: bool = False,
        failure_rate: float = 0.05,
    ) -> StressTestResult:
        start_time = time.time()
        successful = 0
        failed = 0
        loops_detected = 0
        repeats_detected = 0
        cycle_times: list[float] = []
        failure_log: list[dict[str, Any]] = []

        for cycle_num in range(cycles):
            if self._stop_requested:
                break
            if max_duration_seconds is not None and (time.time() - start_time) > max_duration_seconds:
                break

            cycle_start = time.time()
            try:
                repeat_detected = await self._run_test_cycle(
                    cycle_num=cycle_num,
                    inject_failures=inject_failures,
                    failure_rate=failure_rate,
                )
                if repeat_detected:
                    repeats_detected += 1
                successful += 1
            except Exception as exc:
                failed += 1
                if self.supervisor.get_state() in {SupervisorState.WARNING, SupervisorState.CRITICAL, SupervisorState.ABORTED}:
                    loops_detected += 1
                failure_log.append(
                    {
                        "cycle": cycle_num,
                        "error": str(exc),
                        "timestamp": time.time(),
                    }
                )
            cycle_times.append(time.time() - cycle_start)

        total_time = time.time() - start_time
        avg_time = sum(cycle_times) / len(cycle_times) if cycle_times else 0.0
        max_time = max(cycle_times) if cycle_times else 0.0
        min_time = min(cycle_times) if cycle_times else 0.0

        return StressTestResult(
            total_cycles=len(cycle_times),
            successful_cycles=successful,
            failed_cycles=failed,
            infinite_loops_detected=loops_detected,
            repeated_actions_detected=repeats_detected,
            avg_cycle_time=round(avg_time, 6),
            max_cycle_time=round(max_time, 6),
            min_cycle_time=round(min_time, 6),
            failure_log=failure_log,
            performance_metrics={
                "total_duration": round(total_time, 3),
                "cycles_per_second": round((len(cycle_times) / total_time), 3) if total_time > 0 else 0.0,
            },
        )

    async def _run_test_cycle(
        self,
        cycle_num: int,
        inject_failures: bool,
        failure_rate: float,
    ) -> bool:
        self.monitor.record_task_start()
        action = self._build_cycle_action(cycle_num, inject_failures)
        is_safe, reason = self.supervisor.check_action(action)
        if not is_safe:
            self.monitor.record_task_failure("supervisor")
            raise RuntimeError(reason or "supervisor blocked action")

        await asyncio.sleep(0)

        if inject_failures and self._should_inject_failure(cycle_num, failure_rate):
            self.supervisor.record_retry()
            self.monitor.record_retry()
            self.monitor.record_task_failure("injected_failure")
            raise RuntimeError(f"Injected deterministic failure at cycle {cycle_num}")

        self.supervisor.record_step()
        self.supervisor.record_success()
        self.monitor.record_task_success(0.0)
        return cycle_num % 10 == 0 and inject_failures

    @staticmethod
    def _should_inject_failure(cycle_num: int, failure_rate: float) -> bool:
        if failure_rate <= 0.0:
            return False
        interval = max(1, round(1.0 / failure_rate))
        return (cycle_num + 1) % interval == 0

    @staticmethod
    def _build_cycle_action(cycle_num: int, inject_failures: bool) -> dict[str, Any]:
        if inject_failures and cycle_num % 10 == 0:
            return {"action": "repeat_probe", "bucket": "repeat"}
        return {"action": "stress_cycle", "cycle": cycle_num}

    def stop(self) -> None:
        self._stop_requested = True


def run_stress_test_cli() -> None:
    parser = argparse.ArgumentParser(description="Friday stress test")
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--output", type=str, default="stress_test_results.json")
    parser.add_argument("--inject-failures", action="store_true")
    parser.add_argument("--failure-rate", type=float, default=0.05)
    args = parser.parse_args()

    controller = AgentController(AgentConfig(name="stress_test_agent"))
    monitor = Monitor()
    supervisor = Supervisor()
    tester = StressTester(controller, monitor, supervisor)
    result = asyncio.run(
        tester.run_stress_test(
            cycles=args.cycles,
            inject_failures=args.inject_failures,
            failure_rate=args.failure_rate,
        )
    )
    result.save(args.output)
    print(result.to_json())


if __name__ == "__main__":
    run_stress_test_cli()
