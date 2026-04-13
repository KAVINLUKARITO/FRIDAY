from __future__ import annotations

import json
from typing import Any

from config import settings
from runner import run_task

BENCHMARK_TASKS: list[dict[str, str]] = [
    {
        "task": "list files in workspace",
        "expect_tool": "list_files",
        "expect_status": "completed",
    },
    {
        "task": "read the file sample.txt",
        "expect_tool": "read_file",
        "expect_status": "completed",
    },
    {
        "task": "write result to output.txt",
        "expect_tool": "write_file",
        "expect_status": "completed",
    },
    {
        "task": "http get example page",
        "expect_tool": "http_get",
        "expect_status": "completed",
    },
    {
        "task": "parse csv data.csv",
        "expect_tool": "parse_csv",
        "expect_status": "completed",
    },
]


def main() -> int:
    results: list[dict[str, Any]] = []
    passed = 0
    total_steps = 0
    total_duration = 0.0

    for benchmark in BENCHMARK_TASKS:
        state = run_task(benchmark["task"])
        first_tool = state.history[0].tool_name if state.history else None
        status_matches = state.status == benchmark["expect_status"]
        tool_matches = first_tool == benchmark["expect_tool"]
        ok = status_matches and tool_matches
        passed += int(ok)
        total_steps += len(state.history)
        total_duration += sum(record.duration_seconds for record in state.history)

        reason = "PASS"
        if not ok:
            reason = (
                f"expected tool={benchmark['expect_tool']} status={benchmark['expect_status']}; "
                f"got tool={first_tool} status={state.status}"
            )

        results.append(
            {
                "task": benchmark["task"],
                "expected_tool": benchmark["expect_tool"],
                "expected_status": benchmark["expect_status"],
                "result": "PASS" if ok else "FAIL",
                "score": 1 if ok else 0,
                "reason": reason,
                "run_id": state.run_id,
                "steps": len(state.history),
                "duration": sum(record.duration_seconds for record in state.history),
            }
        )

    runtime_dir = settings.db_path.parent
    runtime_dir.mkdir(parents=True, exist_ok=True)
    output_path = runtime_dir / "eval_results.json"
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("| Task | Expected Tool | Expected Status | Result | Score |")
    print("| --- | --- | --- | --- | --- |")
    for result in results:
        print(
            f"| {result['task']} | {result['expected_tool']} | "
            f"{result['expected_status']} | {result['result']} | {result['score']} |"
        )

    average_steps = total_steps / len(BENCHMARK_TASKS)
    average_duration = total_duration / len(BENCHMARK_TASKS)
    print(f"Total score: {passed} / {len(BENCHMARK_TASKS)}")
    print(f"Average steps per run: {average_steps:.2f}")
    print(f"Average duration per run: {average_duration:.6f}")
    print(f"Results saved to: {output_path}")
    return 0 if passed == len(BENCHMARK_TASKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
