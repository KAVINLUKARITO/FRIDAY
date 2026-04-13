"""# FILE: aiworker/chat/interface.py — Conversational interface around the autonomy loop."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
import threading
import time
from typing import Any, Callable, Optional

from aiworker.autonomy.controller import EvolutionController
from aiworker.autonomy.models import EvolutionConfig
from aiworker.config import AIWorkerConfig
from aiworker.governance.audit import AuditEvent, AuditLog
from aiworker.governance.circuit_breaker import CircuitBreaker
from aiworker.governance.policy import PolicyEngine
from aiworker.governance.rate_limiter import RateLimiter
from aiworker.learning.store import LearningStore
from aiworker.llm.claude_backend import ClaudeBackend
from aiworker.llm.deepseek_adapter import DeepSeekAdapter
from aiworker.llm.ollama_backend import OllamaBackend
from aiworker.memory.database import Database


class Intent(str, Enum):
    RUN_GOAL = "run_goal"
    EXPLAIN = "explain"
    SHOW_MEMORY = "show_memory"
    CONFIGURE = "configure"
    STATUS = "status"
    CHAT = "chat"
    HELP = "help"
    STOP = "stop"


class IntentClassifier:
    """Deterministic intent classifier."""

    def classify(self, text: str) -> Intent:
        lower = text.lower().strip()
        if any(token in lower for token in ("stop", "cancel", "abort", "quit", "exit")):
            return Intent.STOP
        if any(token in lower for token in ("status", "running", "progress", "what are you doing")):
            return Intent.STATUS
        if any(token in lower for token in ("memory", "learned", "lessons", "history", "remember")):
            return Intent.SHOW_MEMORY
        if any(token in lower for token in ("use ", "switch to", "set ", "config", "model")):
            return Intent.CONFIGURE
        if any(token in lower for token in ("what did", "explain", "why did", "what happened", "show me")):
            return Intent.EXPLAIN
        if any(token in lower for token in ("help", "what can you", "how do you", "capabilities")):
            return Intent.HELP
        if any(
            lower.startswith(prefix)
            for prefix in ("add", "fix", "refactor", "improve", "create", "build", "write", "implement", "update", "remove")
        ):
            return Intent.RUN_GOAL
        return Intent.CHAT


class ProgressNarrator:
    """Translate audit events into human-readable progress updates."""

    _MESSAGES = {
        "validation_failed": "Hmm, the patch I generated doesn't pass validation. Let me try a different approach.",
        "patch_gen_failed": "The model didn't return a valid patch that time. Retrying.",
        "attempt_succeeded": "Done. I applied the change and the checks passed.",
        "circuit_breaker": "I've hit too many failures in a row. Taking a short pause before trying again.",
        "lessons_stored": "I've learned something from this run and saved it for next time.",
        "context_loaded": "I remember working on something similar before. I'm using that experience now.",
    }

    def narrate(self, event: AuditEvent) -> Optional[str]:
        if event.action == "attempt_succeeded" and event.detail:
            return f"Done. {event.detail}"
        if event.action == "lessons_stored":
            count = event.metadata.get("count", 0)
            return f"I've learned {count} new things from this run. I'll use that next time."
        if event.action in ("blocked", "evolution_halted"):
            return self._MESSAGES["circuit_breaker"]
        return self._MESSAGES.get(event.action)


@dataclass
class _RunState:
    goal: str = ""
    files: tuple[str, ...] = ()
    started: bool = False
    completed: bool = False
    last_response: str = ""


class AIWorkerChat:
    """Interactive chat shell around AIWorker."""

    def __init__(
        self,
        config: AIWorkerConfig,
        patch_generator: Any,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._config = config
        self._patch_generator = patch_generator
        self._stream_callback = stream_callback
        self._classifier = IntentClassifier()
        self._narrator = ProgressNarrator()
        self._pending_goal: Optional[str] = None
        self._current_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._current_audit_log: Optional[AuditLog] = None
        self._last_audit_events: list[AuditEvent] = []
        self._run_state = _RunState()
        self._backend_choice = "claude" if isinstance(patch_generator, ClaudeBackend) else "ollama"

    def chat(self, user_input: str) -> str:
        if self._pending_goal is not None and self._classifier.classify(user_input) not in (
            Intent.STOP,
            Intent.STATUS,
        ):
            return self._start_goal_run(user_input)

        intent = self._classifier.classify(user_input)
        if intent == Intent.RUN_GOAL:
            return self._handle_run_goal(user_input)
        if intent == Intent.SHOW_MEMORY:
            return self._handle_show_memory(user_input)
        if intent == Intent.EXPLAIN:
            return self._handle_explain(user_input)
        if intent == Intent.CONFIGURE:
            return self._handle_configure(user_input)
        if intent == Intent.STATUS:
            return self._handle_status(user_input)
        if intent == Intent.HELP:
            return (
                "I can take engineering goals, explain my last run, show what I've learned, "
                "switch models, and report whether I'm busy."
            )
        if intent == Intent.STOP:
            if self._pending_goal is not None:
                self._pending_goal = None
                return "I stopped waiting for file input."
            if self._current_thread and self._current_thread.is_alive():
                return "I can't safely interrupt a running sandbox mid-attempt. I'll finish the current run and then stop."
            return "Nothing is running."
        return self._handle_chat(user_input)

    def _emit(self, message: str) -> None:
        if self._stream_callback is not None:
            self._stream_callback(message)

    def _normalise_goal(self, text: str) -> str:
        return text.strip()

    def _parse_files(self, text: str) -> tuple[str, ...]:
        lowered = text.strip().lower()
        if lowered == "all":
            root = Path(self._config.workspace_path)
            files = tuple(
                sorted(
                    str(path.relative_to(root))
                    for path in root.rglob("*.py")
                    if path.is_file()
                )
            )
            return files or ("*.py",)
        parts = [segment.strip() for segment in text.replace("\n", ",").split(",")]
        return tuple(part for part in parts if part)

    def _build_generator(self) -> DeepSeekAdapter:
        if self._backend_choice == "claude":
            backend = ClaudeBackend(model=self._config.anthropic_model)
        else:
            backend = OllamaBackend(
                model=self._config.ollama_model,
                timeout=self._config.ollama_timeout,
            )
        return DeepSeekAdapter(
            backend=backend,
            model_name=self._config.ollama_model,
            temperature=self._config.ollama_temperature,
            timeout=self._config.ollama_timeout,
        )

    def _build_controller(
        self,
        goal: str,
        files: tuple[str, ...],
        audit_log: AuditLog,
    ) -> EvolutionController:
        database = Database(self._config.db_path)
        database.initialise()
        policy = PolicyEngine(
            audit_log=audit_log,
            circuit_breaker=CircuitBreaker(
                failure_threshold=self._config.circuit_breaker_threshold
            ),
            rate_limiter=RateLimiter(
                max_attempts=self._config.rate_limit_max,
                window_seconds=self._config.rate_limit_window,
            ),
            health_check_enabled=self._config.health_check_enabled,
        )
        controller_config = EvolutionConfig(
            goal=goal,
            allowed_files=files,
            max_attempts=self._config.max_attempts,
            max_failures=self._config.max_failures,
            confidence_threshold=self._config.confidence_threshold,
            max_lines_changed=self._config.max_lines_changed,
            sandbox_timeout=self._config.sandbox_timeout,
        )
        return EvolutionController(
            config=controller_config,
            policy_engine=policy,
            patch_generator=self._build_generator(),
            workspace_path=self._config.workspace_path,
            database=database,
            audit_log=audit_log,
        )

    def _monitor_progress(self) -> None:
        last_index = 0
        while self._current_thread and self._current_thread.is_alive():
            if self._current_audit_log is not None:
                events = list(self._current_audit_log.all_events())
                for event in events[last_index:]:
                    narrated = self._narrator.narrate(event)
                    if narrated:
                        self._emit(narrated)
                last_index = len(events)
            time.sleep(0.05)
        if self._current_audit_log is not None:
            self._last_audit_events = list(self._current_audit_log.all_events())

    def _run_controller_thread(self, goal: str, files: tuple[str, ...]) -> None:
        try:
            audit_log = AuditLog()
            self._current_audit_log = audit_log
            controller = self._build_controller(goal, files, audit_log)
            result = controller.run()
            if result.success:
                self._run_state.last_response = (
                    f"I finished the work on '{goal}'. The checks passed."
                )
            else:
                self._run_state.last_response = (
                    f"I couldn't finish '{goal}'. I stopped because {result.termination_reason.replace('_', ' ')}."
                )
        except Exception:
            self._run_state.last_response = (
                f"I couldn't start work on '{goal}' because the configured model backend isn't available."
            )
        finally:
            self._run_state.completed = True

    def _handle_run_goal(self, user_input: str) -> str:
        goal = self._normalise_goal(user_input)
        self._pending_goal = goal
        return (
            "I’ll work on that now. Which files should I focus on? "
            "Say 'all' if you want me to decide."
        )

    def _start_goal_run(self, files_text: str) -> str:
        goal = self._pending_goal or ""
        files = self._parse_files(files_text)
        if not files:
            return "I need at least one file path, or say 'all'."

        self._pending_goal = None
        self._run_state = _RunState(goal=goal, files=files, started=True)
        self._current_thread = threading.Thread(
            target=self._run_controller_thread,
            args=(goal, files),
            daemon=True,
        )
        self._current_thread.start()
        self._monitor_thread = threading.Thread(
            target=self._monitor_progress,
            daemon=True,
        )
        self._monitor_thread.start()
        return "I'm on it. I'll stream progress as I go."

    def _handle_show_memory(self, user_input: str) -> str:
        del user_input
        database = Database(self._config.db_path)
        database.initialise()
        store = LearningStore(database)
        lessons = store.get_all_lessons(limit=5)
        if not lessons:
            return "I haven't learned anything persistent yet."
        lines = [f"Here's what I've learned from my last {len(lessons)} runs:"]
        for lesson in lessons:
            lines.append(
                f"- {lesson.summary} (confidence: {lesson.confidence:.0%})"
            )
        return "\n".join(lines)

    def _handle_explain(self, user_input: str) -> str:
        del user_input
        if not self._last_audit_events:
            return "I haven't run anything yet."
        narrated = [
            self._narrator.narrate(event) or event.detail
            for event in self._last_audit_events
        ]
        return "Here's what happened:\n" + "\n".join(
            f"- {line}" for line in narrated if line
        )

    def _handle_configure(self, user_input: str) -> str:
        lower = user_input.lower()
        if "claude" in lower:
            self._backend_choice = "claude"
            self._config = replace(self._config, anthropic_model=self._extract_model_name(user_input, self._config.anthropic_model))
            return f"Switched to {self._config.anthropic_model}. I'll use that from now on."
        if "deepseek" in lower or "ollama" in lower:
            self._backend_choice = "ollama"
            self._config = replace(self._config, ollama_model=self._extract_model_name(user_input, self._config.ollama_model))
            return f"Switched to {self._config.ollama_model}. I'll use that from now on."
        return "I couldn't parse that config change. Tell me which model to use."

    def _extract_model_name(self, text: str, default: str) -> str:
        if '"' in text:
            parts = text.split('"')
            if len(parts) >= 3 and parts[1].strip():
                return parts[1].strip()
        return default

    def _handle_status(self, user_input: str) -> str:
        del user_input
        if self._current_thread and self._current_thread.is_alive():
            attempt_count = 0
            if self._current_audit_log is not None:
                attempt_count = sum(
                    1 for event in self._current_audit_log.all_events()
                    if event.action == "attempt_started"
                )
            return f"I'm working on '{self._run_state.goal}'. Current attempt: {max(1, attempt_count)}."
        if self._run_state.completed and self._run_state.last_response:
            return self._run_state.last_response
        return "I'm ready. Give me a goal and I'll get to work."

    def _handle_chat(self, user_input: str) -> str:
        lesson_count = 0
        try:
            database = Database(self._config.db_path)
            database.initialise()
            lesson_count = LearningStore(database).lesson_count()
        except Exception:
            lesson_count = 0

        status = "busy" if self._current_thread and self._current_thread.is_alive() else "idle"
        prompt = "\n".join(
            [
                "You are AIWorker, an autonomous software engineering agent.",
                "You speak in first person, directly and confidently.",
                f"You have {lesson_count} lessons in memory from past runs.",
                f"You are currently {status}.",
                "Keep responses concise and practical.",
                "",
                f"User: {user_input}",
            ]
        )

        backend = getattr(self._patch_generator, "backend", None) or self._patch_generator
        if hasattr(backend, "generate"):
            try:
                response = backend.generate(prompt)
                cleaned = str(response).strip()
                return cleaned or "I don't have anything useful to add right now."
            except Exception:
                return "I can't answer that through my model backend right now."
        return "I can help with code goals, status, memory, and explanations."
