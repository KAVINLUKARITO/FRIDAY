from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from config import cfg
from config import settings as root_settings
from executor import Executor
from friday.planner import Planner
from memory.skills import SkillLibrary
from memory.store import read_memory, write_goal_progress
from observability.logger import logger

try:
    from aiworker.runner import run_bug_bounty, run_trading_lab  # noqa: F401
except Exception:  # pragma: no cover - optional legacy surface
    run_bug_bounty = None  # type: ignore[assignment]
    run_trading_lab = None  # type: ignore[assignment]

try:
    from friday_runner import run_task  # noqa: F401
    from friday_runner import settings  # noqa: F401
    import friday_runner as legacy_runner
except Exception:  # pragma: no cover - optional legacy surface
    legacy_runner = None  # type: ignore[assignment]
    run_task = None  # type: ignore[assignment]
    settings = None  # type: ignore[assignment]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the AIWorker audit-compatible task runner.")
    parser.add_argument("task", nargs="?", help="Task description to execute.")
    parser.add_argument("--dry-run", action="store_true", help="Plan the task and print the plan.")
    parser.add_argument("--verbose", action="store_true", help="Print the recorded run trace after execution.")
    parser.add_argument("--task-file", help="Read one task per line from a file and execute them sequentially.")
    parser.add_argument("--json", action="store_true", help="Delegate to the legacy Friday JSON mode.")
    parser.add_argument("--memory", action="store_true", help="Delegate to the legacy Friday memory mode.")
    parser.add_argument("--knowledge", action="store_true", help="Delegate to the legacy Friday knowledge mode.")
    parser.add_argument("--stats", action="store_true", help="Delegate to the legacy Friday stats mode.")
    parser.add_argument("--dashboard", action="store_true", help="Start the observability dashboard")
    parser.add_argument("--multi-agent", action="store_true", help="Start multi-agent supervisor")
    parser.add_argument("--goal", type=str, default=None, help="High-level goal to decompose and execute across runs")
    return parser


def _print_verbose_trace() -> None:
    run_id = getattr(logger, "_run_id", "")
    if not run_id:
        return
    trace_path = Path("observability/runs") / f"{run_id}.json"
    if trace_path.exists():
        print(trace_path.read_text(encoding="utf-8"))


def _run_single_task(task: str, *, dry_run: bool, verbose: bool, emit_output: bool = True) -> int:
    root_settings.workspace_dir = Path.cwd()
    planner = Planner()
    if dry_run:
        plan = planner.plan(task, read_memory(task))
        if emit_output:
            print(json.dumps(plan, indent=2))
        return 0
    result = Executor().run(task)
    if emit_output:
        print(json.dumps(result, indent=2, default=str))
    if verbose and emit_output:
        _print_verbose_trace()
    return 0


def _run_task_file(task_file: str, *, dry_run: bool, verbose: bool) -> int:
    tasks = [
        line.strip()
        for line in Path(task_file).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summaries: list[dict[str, Any]] = []
    for task in tasks:
        exit_code = _run_single_task(task, dry_run=dry_run, verbose=verbose, emit_output=False)
        summaries.append({"task": task, "exit_code": exit_code})
    print(json.dumps(summaries, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root_settings.workspace_dir = Path.cwd()

    if args.dashboard:
        try:
            import uvicorn
            from dashboard.server import app, dashboard_runtime_error
        except Exception as exc:
            print(f"dashboard startup failed: {exc}")
            return 1
        runtime_error = dashboard_runtime_error()
        if runtime_error or app is None:
            print(runtime_error or "dashboard dependencies unavailable")
            return 1
        uvicorn.run(
            app,
            host=cfg.get("dashboard_host", "127.0.0.1"),
            port=int(cfg.get("dashboard_port", 8080)),
        )
        return 0
    if args.multi_agent:
        from agents.supervisor import Supervisor

        Supervisor().run()
        return 0
    if args.goal:
        planner = Planner()
        executor = Executor()
        sub_goals = planner.decompose_goal(args.goal)
        print(f"[GOAL] Decomposed into {len(sub_goals)} sub-goals:")
        for index, sub_goal in enumerate(sub_goals, 1):
            print(f"  {index}. {sub_goal}")
        results = []
        for sub_goal in sub_goals:
            print(f"\n[GOAL] Executing sub-goal: {sub_goal}")
            result = executor.run(sub_goal)
            print(json.dumps(result, indent=2, default=str))
            results.append({"sub_goal": sub_goal, "result": result})
            if not result.get("goal_achieved"):
                print("[GOAL] Sub-goal failed. Stopping.")
                break
        achieved = sum(1 for item in results if item["result"].get("goal_achieved"))
        write_goal_progress(args.goal, sub_goals, results)
        promoted = SkillLibrary().promote_from_goals()
        logger.log("EXECUTOR", "SKILLS_PROMOTED", {"count": promoted})
        suggested_next_task = next(
            (
                str(item["result"].get("suggested_next_task"))
                for item in reversed(results)
                if item["result"].get("suggested_next_task")
            ),
            None,
        )
        print(f"\n[GOAL] Completed {achieved}/{len(results)} sub-goals.")
        print(
            json.dumps(
                {
                    "goal": args.goal,
                    "sub_goals": sub_goals,
                    "completed": achieved,
                    "total": len(results),
                    "suggested_next_task": suggested_next_task,
                },
                indent=2,
            )
        )
        return 0

    if args.json or args.memory or args.knowledge or args.stats:
        if legacy_runner is None:
            parser.error("legacy Friday mode is unavailable in this environment")
        return legacy_runner.main(argv)
    if args.task is None and not args.task_file:
        return _run_single_task("", dry_run=args.dry_run, verbose=args.verbose)
    if args.task_file:
        return _run_task_file(args.task_file, dry_run=args.dry_run, verbose=args.verbose)
    return _run_single_task(str(args.task), dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
