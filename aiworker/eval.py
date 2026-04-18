from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aiworker.config import settings
from aiworker.message_bus import EventType, bus
from aiworker.runner import run_bug_bounty, run_trading_lab
from aiworker.storage import Storage

BUG_BOUNTY_BENCHMARKS: list[dict[str, str]] = [
    {"task": "scan localhost for headers", "expect_tool": "scan_headers", "expect_event": "report.ready"},
    {"task": "check sql injection on target", "expect_tool": "check_sql_injection"},
    {"task": "check xss on target", "expect_tool": "check_xss"},
    {"task": "port scan localhost", "expect_tool": "port_scan"},
    {"task": "parse html from target", "expect_tool": "parse_html"},
]


def main() -> int:
    results: list[dict[str, Any]] = []
    storage = Storage(settings.db_path)
    total_checks = 0
    passed_checks = 0

    for benchmark in BUG_BOUNTY_BENCHMARKS:
        run_id = run_bug_bounty(settings.bug_bounty_target)
        steps = storage.get_run_steps(run_id)
        events = bus.history(run_id)
        tool_seen = any(step.tool_name == benchmark["expect_tool"] for step in steps)
        event_seen = True
        if "expect_event" in benchmark:
            event_seen = any(event.event_type.value == benchmark["expect_event"] for event in events)
        passed = tool_seen and event_seen
        total_checks += 1
        passed_checks += int(passed)
        results.append(
            {
                "subsystem": "bug_bounty",
                "task": benchmark["task"],
                "expected_tool": benchmark["expect_tool"],
                "expected_event": benchmark.get("expect_event"),
                "result": "PASS" if passed else "FAIL",
                "run_id": run_id,
            }
        )

    trading_run_id = run_trading_lab(30.0)
    trading_steps = storage.get_run_steps(trading_run_id)
    trading_events = bus.history(trading_run_id)
    trading_checks = [
        (
            "At least 5 MARKET_DATA_UPDATED events published",
            sum(1 for event in trading_events if event.event_type is EventType.MARKET_DATA_UPDATED) >= 5,
        ),
        (
            "At least 1 SIGNAL_GENERATED event published",
            sum(1 for event in trading_events if event.event_type is EventType.SIGNAL_GENERATED) >= 1,
        ),
        (
            "Portfolio balance tracked correctly",
            any(event.event_type is EventType.PORTFOLIO_UPDATED for event in trading_events),
        ),
        (
            "All step records stored in SQLite",
            len(trading_steps) >= sum(
                1
                for event in trading_events
                if event.event_type in {EventType.MARKET_DATA_UPDATED, EventType.SIGNAL_GENERATED, EventType.ORDER_EXECUTED}
            ),
        ),
    ]

    for description, passed in trading_checks:
        total_checks += 1
        passed_checks += int(passed)
        results.append(
            {
                "subsystem": "trading",
                "task": description,
                "expected_tool": None,
                "expected_event": None,
                "result": "PASS" if passed else "FAIL",
                "run_id": trading_run_id,
            }
        )

    output_path = settings.db_path.parent / "eval_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("| Subsystem | Task | Result |")
    print("| --- | --- | --- |")
    for result in results:
        print(f"| {result['subsystem']} | {result['task']} | {result['result']} |")
    print(f"Score: {passed_checks} / {total_checks}")
    print(f"Saved results: {output_path}")
    return 0 if passed_checks == total_checks else 1


if __name__ == "__main__":
    raise SystemExit(main())
