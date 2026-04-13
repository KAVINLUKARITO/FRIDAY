from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from executor import Executor
from friday.config import settings
from friday.identity import FridayIdentity
from friday.knowledge.graph import KnowledgeGraph
from friday.memory.episodic import EpisodicMemory
from friday.memory.retrieval import RetrievalEngine
from friday.planner import AdaptivePlanner
from friday.reflection import ReflectionEngine
from logger import get_logger
from planner import AgentState
from storage import StepRecord, Storage
from validator import ValidationError, Validator
from verifier import VerificationStatus, Verifier

Planner = AdaptivePlanner


def _compat_attr(name: str, default: Any) -> Any:
    alias_module = sys.modules.get("runner")
    if alias_module is not None and hasattr(alias_module, name):
        return getattr(alias_module, name)
    return default


def _bootstrap_workspace(workspace_dir: Path) -> None:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    bootstrap_files: dict[str, str] = {
        "sample.txt": "sample content\n",
        "sample.csv": "name,value\nalpha,1\nbeta,2\n",
        "data.csv": "name,value\nalpha,1\nbeta,2\n",
    }
    for relative_path, content in bootstrap_files.items():
        target = workspace_dir / relative_path
        if not target.exists():
            target.write_text(content, encoding="utf-8")


def _build_friday_components(current_settings: Any) -> tuple[EpisodicMemory, RetrievalEngine, KnowledgeGraph, ReflectionEngine]:
    episodic_memory = EpisodicMemory(current_settings.db_path)
    retrieval = RetrievalEngine(episodic_memory)
    knowledge_graph = KnowledgeGraph(current_settings.db_path)
    reflection_engine = ReflectionEngine(episodic_memory)
    return episodic_memory, retrieval, knowledge_graph, reflection_engine


def _log_startup_identity(logger: Any, episodic_memory: EpisodicMemory, knowledge_graph: KnowledgeGraph) -> None:
    logger.info(FridayIdentity.BANNER.strip("\n"))
    memory_stats = episodic_memory.get_stats()
    knowledge_stats = knowledge_graph.summarize()
    logger.info(FridayIdentity.introduce(memory_stats, knowledge_stats))


def run_task(task: str) -> AgentState:
    run_id = str(uuid4())
    current_settings = _compat_attr("settings", settings)
    logger = get_logger("friday_runner")
    storage = Storage(current_settings.db_path)
    storage.init_db()
    _bootstrap_workspace(current_settings.workspace_dir)

    episodic_memory, retrieval, knowledge_graph, reflection_engine = _build_friday_components(current_settings)
    _log_startup_identity(logger, episodic_memory, knowledge_graph)

    context = retrieval.get_context_for_task(task)
    logger.info("Memory confidence for task: %.0f%%", float(context["confidence"]) * 100.0)
    if context["similar_past_tasks"]:
        logger.info(
            "Friday recalled %s similar task(s) and tools=%s",
            len(context["similar_past_tasks"]),
            context["recommended_tools"],
        )

    planner_factory = _compat_attr("Planner", AdaptivePlanner)
    try:
        planner = planner_factory(retrieval)
    except TypeError:
        planner = planner_factory()

    validator_factory = _compat_attr("Validator", Validator)
    executor_factory = _compat_attr("Executor", Executor)
    verifier_factory = _compat_attr("Verifier", Verifier)
    validator = validator_factory()
    executor = executor_factory()
    verifier = verifier_factory()

    state = AgentState(run_id=run_id, task=task)
    compat_time = _compat_attr("time", time)
    pending_action: dict[str, Any] | None = None

    while state.step_number <= current_settings.max_steps and state.status == "running":
        raw_action = pending_action if pending_action is not None else planner.plan(state)
        pending_action = None

        try:
            validated_action = validator.validate(raw_action)
        except ValidationError as exc:
            logger.error("validation failed at step %s: %s", state.step_number, exc)
            state.status = "aborted"
            break

        result = executor.run(validated_action)
        verification_result = verifier.verify(validated_action, result)

        record = StepRecord(
            run_id=state.run_id,
            step_number=validated_action.step_number,
            tool_name=validated_action.tool_name,
            parameters=validated_action.parameters,
            reason=validated_action.reason,
            verification_status=verification_result.status.value,
            output_summary=str(result.output)[:500],
            error=result.error,
            duration_seconds=result.duration_seconds,
            timestamp=verification_result.verified_at,
        )
        storage.save_step(record)
        state.history.append(record)

        logger.info(
            "step=%s tool=%s status=%s duration=%.6f",
            state.step_number,
            validated_action.tool_name,
            verification_result.status.value,
            result.duration_seconds,
        )

        if verification_result.status is VerificationStatus.SUCCESS:
            if not planner.has_more_steps(state):
                state.status = "completed"
                break
            state.step_number += 1
            state.retries = 0
            continue

        if state.retries < current_settings.max_retries:
            state.retries += 1
            compat_time.sleep(current_settings.retry_backoff_base * (2 ** (state.retries - 1)))
            continue

        if state.replans < current_settings.max_replans:
            state.replans += 1
            state.retries = 0
            pending_action = planner.replan(state, verification_result.reason)
            continue

        state.status = "aborted"
        break

    if state.step_number > current_settings.max_steps:
        state.status = "step_limit_reached"

    summary = storage.get_summary(state.run_id)
    logger.info(
        "run_id=%s final_status=%s total_steps=%s total_duration=%.6f",
        state.run_id,
        state.status,
        summary["total_steps"],
        summary["total_duration"],
    )

    episode = reflection_engine.reflect(state, state.history)
    knowledge_graph.learn_from_episode(episode)
    trend = reflection_engine.get_performance_trend()
    logger.info("Reflection summary: %s", episode.reflection)
    logger.info("Friday performance trend: %s", trend["trend"])
    logger.info("Recommendation: %s", trend["recommendation"])
    return state


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Friday, the AGI-progressive task agent.")
    parser.add_argument("task", nargs="?", help="Task description for Friday to execute.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the final Friday state as JSON.",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Show Friday's memory summary and exit.",
    )
    parser.add_argument(
        "--knowledge",
        action="store_true",
        help="Show Friday's knowledge graph summary and exit.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show Friday episodic memory statistics and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.memory:
        episodic_memory, retrieval, knowledge_graph, _ = _build_friday_components(settings)
        logger = get_logger("friday_runner")
        _log_startup_identity(logger, episodic_memory, knowledge_graph)
        print(retrieval.summarize_memory())
        return 0
    if args.knowledge:
        episodic_memory, _, knowledge_graph, _ = _build_friday_components(settings)
        logger = get_logger("friday_runner")
        _log_startup_identity(logger, episodic_memory, knowledge_graph)
        print(json.dumps(knowledge_graph.summarize(), indent=2))
        return 0
    if args.stats:
        episodic_memory, _, knowledge_graph, _ = _build_friday_components(settings)
        logger = get_logger("friday_runner")
        _log_startup_identity(logger, episodic_memory, knowledge_graph)
        print(json.dumps(episodic_memory.get_stats(), indent=2))
        return 0
    if not args.task:
        parser.error("a task is required unless --memory, --knowledge, or --stats is used")

    final_state = run_task(args.task)
    if args.json:
        print(final_state.model_dump_json(indent=2))
    else:
        print(
            json.dumps(
                final_state.model_dump(mode="json"),
                indent=2,
                default=str,
            )
        )
    return 0 if final_state.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
