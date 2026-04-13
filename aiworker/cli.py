"""Minimal CLI interface for the aiworker system.

All output is structured JSON printed to stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from typing import Any, List, Sequence

from aiworker.llm.proposer import generate_patch_from_goal
from aiworker.advisory.advisor import request_advice
from aiworker.dashboard.server import start_dashboard_server
from aiworker.memory.database import Database
from aiworker.memory.repository import MemoryRepository
from aiworker.monitor.control import control_plane
from aiworker.planning.models import Plan, PlanStep
from aiworker.planning.simulator import simulate_plan
from aiworker.retrieval.search import search_web
from aiworker.retrieval.summarizer import summarize_results
from aiworker.runtime.engine import runtime_engine
from aiworker.self_modify.change_request import ChangeRequest
from aiworker.self_modify.patch_validator import (
    validate_patch, _extract_files, _count_lines,
)
from aiworker.voice.interface import start_voice_listener

_DEFAULT_DB_PATH = "aiworker.db"


def _get_db_path() -> str:
    return os.environ.get("AIWORKER_DB_PATH", _DEFAULT_DB_PATH)


def _read_patch_file(path: str) -> str:
    resolved = os.path.realpath(path)
    if not os.path.isfile(resolved):
        return ""
    with open(resolved, "r") as fh:
        return fh.read()


def _json_out(data: object) -> None:
    json.dump(data, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def execute_control_command(command: str, **kwargs: Any) -> dict[str, Any]:
    if command == "start-learning":
        goal = str(kwargs.get("goal") or "dashboard-learning-session")
        return control_plane.start_learning(goal=goal)
    if command == "stop-loop":
        return control_plane.stop_loop()
    if command == "status-report":
        return control_plane.status_report()
    if command == "apply-patch":
        if kwargs.get("admin"):
            control_plane.update_policy(read_only=False, admin_mode=True)
        return control_plane.apply_patch(event_id=kwargs.get("patch_id"))
    if command == "rollback-patch":
        if kwargs.get("admin"):
            control_plane.update_policy(admin_mode=True)
        return control_plane.rollback_patch(event_id=kwargs.get("patch_id"))
    if command == "policy":
        return control_plane.update_policy(
            read_only=kwargs.get("read_only"),
            admin_mode=kwargs.get("admin_mode"),
            auto_apply=kwargs.get("auto_apply"),
        )
    if command == "runtime-start":
        return control_plane.start_runtime(goal=kwargs.get("goal"))
    if command == "runtime-stop":
        return control_plane.stop_runtime()
    if command == "runtime-status":
        return control_plane.runtime_status()
    raise ValueError(f"Unsupported control command: {command}")


def _cmd_validate(args: argparse.Namespace) -> int:
    patch_content = _read_patch_file(args.patch)
    if not patch_content:
        _json_out({"error": f"Cannot read patch file: {args.patch}"})
        return 1
    files = _extract_files(patch_content)
    cr = ChangeRequest(
        goal="validate-cli",
        allowed_files=files if files else ["placeholder.py"],
        max_lines_changed=200, risk_level="low",
    )
    result = validate_patch(patch_content, cr)
    _json_out(result.to_dict())
    return 0 if result.valid else 1


def _cmd_simulate(args: argparse.Namespace) -> int:
    patch_content = _read_patch_file(args.patch)
    if not patch_content:
        _json_out({"error": f"Cannot read patch file: {args.patch}"})
        return 1
    files = _extract_files(patch_content)
    added, removed = _count_lines(patch_content)
    steps: List[PlanStep] = [
        PlanStep(step_id=i, description=f"Modify {f}",
                 estimated_risk="low", requires_tests=True)
        for i, f in enumerate(files, 1)
    ]
    complexity = min(1.0, (added + removed) / 200.0)
    plan = Plan(goal="simulate-cli", steps=tuple(steps),
                complexity_score=complexity)
    _json_out(asdict(simulate_plan(plan)))
    return 0


def _cmd_advisory(args: argparse.Namespace) -> int:
    result = request_advice(
        goal=args.goal, plan_summary="CLI advisory request",
        simulation_success=0.5, confidence_score=0.5,
    )
    _json_out(asdict(result))
    return 0


def _cmd_memory_stats(args: argparse.Namespace) -> int:
    db = Database(_get_db_path())
    db.initialise()
    with db.connect() as conn:
        counts = {}
        for tbl in ("change_attempts", "validation_results",
                    "sandbox_results", "approval_results"):
            counts[tbl] = conn.execute(
                f"SELECT COUNT(*) FROM {tbl}"
            ).fetchone()[0]
    _json_out({"db_path": _get_db_path(), **counts})
    return 0


def _cmd_list_attempts(args: argparse.Namespace) -> int:
    db = Database(_get_db_path())
    db.initialise()
    repo = MemoryRepository(db)
    records = repo.get_last_n_attempts(n=20)
    _json_out([{
        "id": r.id, "goal": r.goal, "risk_level": r.risk_level,
        "allowed_files": r.get_allowed_files_list(), "timestamp": r.timestamp,
    } for r in records])
    return 0

def _cmd_system_info(args: argparse.Namespace) -> int:
    info = {
        "python_version": sys.version,
        "working_directory": os.getcwd(),
        "database_path": _get_db_path(),
    }
    _json_out(info)
    return 0

def _cmd_generate_plan(args: argparse.Namespace) -> int:
    # Very simple deterministic plan generator
    goal = args.goal
    research_summary = ""
    try:
        research_results = search_web(goal)
        research_summary = summarize_results(research_results)
    except Exception:
        research_summary = ""

    analysis_description = f"Analyze goal: {goal}"
    if research_summary:
        analysis_description = f"{analysis_description} | Research context: {research_summary}"

    steps = [
        PlanStep(
            step_id=1,
            description=analysis_description,
            estimated_risk="low",
            requires_tests=True,
        ),
        PlanStep(
            step_id=2,
            description="Identify affected modules",
            estimated_risk="low",
            requires_tests=True,
        ),
        PlanStep(
            step_id=3,
            description="Implement changes and update tests",
            estimated_risk="medium",
            requires_tests=True,
        ),
    ]

    plan = Plan(
        goal=goal,
        steps=tuple(steps),
        complexity_score=0.3,
    )

    _json_out(asdict(plan))
    return 0

import uuid

def _cmd_generate_patch(args: argparse.Namespace) -> int:
    goal = args.goal
    os.makedirs("workspace", exist_ok=True)

    patch_id = uuid.uuid4().hex[:8]
    patch_path = f"workspace/generated_{patch_id}.diff"

    patch_content = f"""diff --git a/example.txt b/example.txt
new file mode 100644
--- /dev/null
+++ b/example.txt
@@ -0,0 +1,3 @@
+# Goal
+# {goal}
+print("Auto-generated placeholder")
"""

    with open(patch_path, "w") as f:
        f.write(patch_content)

    _json_out({
        "goal": goal,
        "patch_file": patch_path,
        "note": "Template patch generated. Review before validation."
    })
    return 0

def _cmd_generate_patch_llm(args: argparse.Namespace) -> int:
    try:
        path = generate_patch_from_goal(args.goal)
        _json_out({
            "goal": args.goal,
            "patch_file": path,
            "source": "ollama"
        })
        return 0
    except Exception as e:
        _json_out({"error": str(e)})
        return 1


def _cmd_start_learning(args: argparse.Namespace) -> int:
    _json_out(execute_control_command("start-learning", goal=args.goal))
    return 0


def _cmd_stop_loop(args: argparse.Namespace) -> int:
    _json_out(execute_control_command("stop-loop"))
    return 0


def _cmd_status_report(args: argparse.Namespace) -> int:
    _json_out(execute_control_command("status-report"))
    return 0


def _cmd_apply_patch(args: argparse.Namespace) -> int:
    result = execute_control_command(
        "apply-patch",
        patch_id=args.patch_id,
        admin=args.admin,
    )
    _json_out(result)
    return 0 if result.get("applied") else 1


def _cmd_rollback_patch(args: argparse.Namespace) -> int:
    result = execute_control_command(
        "rollback-patch",
        patch_id=args.patch_id,
        admin=args.admin,
    )
    _json_out(result)
    return 0 if result.get("rolled_back") else 1


def _cmd_policy(args: argparse.Namespace) -> int:
    read_only = None
    if getattr(args, "read_only", False):
        read_only = True
    elif getattr(args, "read_write", False):
        read_only = False

    admin_mode = None
    if getattr(args, "admin_mode", False):
        admin_mode = True
    elif getattr(args, "disable_admin_mode", False):
        admin_mode = False

    auto_apply = None
    if getattr(args, "auto_apply", False):
        auto_apply = True
    elif getattr(args, "disable_auto_apply", False):
        auto_apply = False

    _json_out(
        execute_control_command(
            "policy",
            read_only=read_only,
            admin_mode=admin_mode,
            auto_apply=auto_apply,
        )
    )
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    if args.check:
        _json_out({"host": args.host, "port": args.port, "service": "dashboard"})
        return 0
    start_dashboard_server(host=args.host, port=args.port)
    return 0


def _cmd_voice(args: argparse.Namespace) -> int:
    result = start_voice_listener(
        once=args.once or bool(args.command),
        command_text=args.command,
        admin=args.admin,
    )
    if result is not None:
        _json_out(result)
    return 0


def _cmd_runtime_run(args: argparse.Namespace) -> int:
    runtime_engine.sleep_interval = max(0.0, float(args.sleep_interval))
    runtime_engine.start(
        goal=args.goal,
        background=False,
        max_cycles=args.max_cycles,
    )
    _json_out(runtime_engine.status())
    return 0


def _cmd_runtime_stop(args: argparse.Namespace) -> int:
    del args
    _json_out(runtime_engine.stop())
    return 0


def _cmd_runtime_status(args: argparse.Namespace) -> int:
    del args
    _json_out(runtime_engine.status())
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aiworker", description="Minimal CLI for the aiworker system.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="Validate a unified diff patch.")
    p.add_argument("--patch", required=True, help="Path to patch file.")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("simulate", help="Simulate a plan from a patch.")
    p.add_argument("--patch", required=True, help="Path to patch file.")
    p.set_defaults(func=_cmd_simulate)

    p = sub.add_parser("advisory", help="Request LLM advisory for a goal.")
    p.add_argument("--goal", required=True, help="Goal description text.")
    p.set_defaults(func=_cmd_advisory)

    p = sub.add_parser("generate-plan", help="Generate a deterministic plan from a goal.")
    p.add_argument("--goal", required=True, help="Goal description.") 
    p.set_defaults(func=_cmd_generate_plan)

    p = sub.add_parser("generate-patch", help="Generate a template patch from a goal.")
    p.add_argument("--goal", required=True, help="Goal description.")
    p.set_defaults(func=_cmd_generate_patch)

    p = sub.add_parser("generate-patch-llm", help="Generate patch using local LLM.")
    p.add_argument("--goal", required=True, help="Goal description.")
    p.set_defaults(func=_cmd_generate_patch_llm)

    p = sub.add_parser("start-learning", help="Start the autonomy learning loop state.")
    p.add_argument("--goal", default="dashboard-learning-session", help="Learning goal label.")
    p.set_defaults(func=_cmd_start_learning)

    p = sub.add_parser("stop-loop", help="Pause the autonomy loop state.")
    p.set_defaults(func=_cmd_stop_loop)

    p = sub.add_parser("status-report", help="Show telemetry-backed system status.")
    p.set_defaults(func=_cmd_status_report)

    p = sub.add_parser("apply-patch", help="Approve and apply the latest tracked patch.")
    p.add_argument("--patch-id", help="Specific patch event identifier.", default=None)
    p.add_argument("--admin", action="store_true", help="Enable admin mode for local approval.")
    p.set_defaults(func=_cmd_apply_patch)

    p = sub.add_parser("rollback-patch", help="Rollback the latest tracked patch.")
    p.add_argument("--patch-id", help="Specific patch event identifier.", default=None)
    p.add_argument("--admin", action="store_true", help="Enable admin mode for local rollback.")
    p.set_defaults(func=_cmd_rollback_patch)

    p = sub.add_parser("policy", help="Update dashboard policy controls.")
    p.add_argument("--read-only", action="store_true", help="Enable read-only mode.")
    p.add_argument("--read-write", action="store_true", help="Disable read-only mode.")
    p.add_argument("--admin-mode", action="store_true", help="Enable admin mode.")
    p.add_argument("--disable-admin-mode", action="store_true", help="Disable admin mode.")
    p.add_argument("--auto-apply", action="store_true", help="Enable auto-apply policy.")
    p.add_argument("--disable-auto-apply", action="store_true", help="Disable auto-apply policy.")
    p.set_defaults(func=_cmd_policy)

    p = sub.add_parser("dashboard", help="Start the monitoring dashboard backend.")
    p.add_argument("--host", default="127.0.0.1", help="Dashboard host.")
    p.add_argument("--port", type=int, default=8000, help="Dashboard port.")
    p.add_argument("--check", action="store_true", help="Validate startup configuration without running.")
    p.set_defaults(func=_cmd_dashboard)

    p = sub.add_parser("voice", help="Start the voice command listener.")
    p.add_argument("--once", action="store_true", help="Process a single command then exit.")
    p.add_argument("--command", help="Text command fallback for non-microphone environments.")
    p.add_argument("--admin", action="store_true", help="Enable admin mode for apply/rollback commands.")
    p.set_defaults(func=_cmd_voice)

    p = sub.add_parser("run", help="Start the continuous AIWorker runtime loop.")
    p.add_argument("--goal", help="Optional goal override for the next runtime cycle.")
    p.add_argument("--sleep-interval", type=float, default=2.0, help="Seconds to sleep between cycles.")
    p.add_argument("--max-cycles", type=int, help="Optional maximum cycles for bounded execution.")
    p.set_defaults(func=_cmd_runtime_run)

    sub.add_parser("stop", help="Stop the continuous AIWorker runtime loop.").set_defaults(func=_cmd_runtime_stop)
    sub.add_parser("status", help="Show continuous runtime status.").set_defaults(func=_cmd_runtime_status)

    sub.add_parser("memory-stats", help="Show memory DB statistics.").set_defaults(func=_cmd_memory_stats)
    sub.add_parser("list-attempts", help="List recent change attempts.").set_defaults(func=_cmd_list_attempts)
    sub.add_parser("system-info", help="Show system runtime information.").set_defaults(func=_cmd_system_info)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
