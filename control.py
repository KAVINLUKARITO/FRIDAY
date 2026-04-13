from __future__ import annotations

import signal
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from logger import get_logger


class AgentControlState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class AgentConfig:
    name: str
    max_tasks: int = 1000
    enable_monitoring: bool = True
    enable_supervisor: bool = True
    log_level: str = "INFO"


class AgentController:
    """Lifecycle controller for runtime, monitoring, and deployment gates."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.state = AgentControlState.STOPPED
        self._runtime: Any | None = None
        self._monitor: Any | None = None
        self._supervisor: Any | None = None
        self._shutdown_hooks: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._logger = get_logger("control")

    def register_runtime(self, runtime: Any) -> None:
        self._runtime = runtime

    def register_monitor(self, monitor: Any) -> None:
        self._monitor = monitor

    def register_supervisor(self, supervisor: Any) -> None:
        self._supervisor = supervisor

    def add_shutdown_hook(self, hook: Callable[[], None]) -> None:
        self._shutdown_hooks.append(hook)

    def start_agent(self) -> bool:
        with self._lock:
            if self.state in {AgentControlState.RUNNING, AgentControlState.STARTING}:
                return False
            self.state = AgentControlState.STARTING

        try:
            self._register_signal_handlers()
            if self._monitor is not None:
                self._monitor.log_event("agent", "INFO", f"Agent {self.config.name} starting")
            if self._runtime is not None:
                started = self._runtime.start()
                if started is False:
                    raise RuntimeError("runtime failed to start")
            with self._lock:
                self.state = AgentControlState.RUNNING
            self._logger.info("Agent started: %s", self.config.name)
            return True
        except Exception as exc:
            with self._lock:
                self.state = AgentControlState.ERROR
            if self._monitor is not None:
                self._monitor.log_event("agent", "CRITICAL", f"Agent start failed: {exc}")
            self._logger.error("Failed to start agent %s: %s", self.config.name, exc)
            return False

    def stop_agent(self, graceful: bool = True, timeout: float = 30.0) -> bool:
        del graceful, timeout
        with self._lock:
            if self.state is AgentControlState.STOPPED:
                return True
            self.state = AgentControlState.STOPPING

        try:
            for hook in list(self._shutdown_hooks):
                try:
                    hook()
                except Exception as exc:
                    self._logger.error("Shutdown hook error: %s", exc)
            if self._runtime is not None:
                self._runtime.stop()
            if self._monitor is not None:
                self._monitor.log_event("agent", "INFO", f"Agent {self.config.name} stopped")
            with self._lock:
                self.state = AgentControlState.STOPPED
            self._shutdown_event.set()
            self._logger.info("Agent stopped: %s", self.config.name)
            return True
        except Exception as exc:
            with self._lock:
                self.state = AgentControlState.ERROR
            self._logger.error("Error stopping agent %s: %s", self.config.name, exc)
            return False

    def pause_agent(self) -> bool:
        with self._lock:
            if self.state is not AgentControlState.RUNNING:
                return False
            if self._runtime is not None:
                self._runtime.pause()
            self.state = AgentControlState.PAUSED
        if self._monitor is not None:
            self._monitor.log_event("agent", "INFO", f"Agent {self.config.name} paused")
        return True

    def resume_agent(self) -> bool:
        with self._lock:
            if self.state is not AgentControlState.PAUSED:
                return False
            if self._runtime is not None:
                self._runtime.resume()
            self.state = AgentControlState.RUNNING
        if self._monitor is not None:
            self._monitor.log_event("agent", "INFO", f"Agent {self.config.name} resumed")
        return True

    def get_status(self) -> dict[str, Any]:
        status = {
            "name": self.config.name,
            "state": self.state.value,
            "config": {
                "max_tasks": self.config.max_tasks,
                "enable_monitoring": self.config.enable_monitoring,
                "enable_supervisor": self.config.enable_supervisor,
            },
        }
        if self._monitor is not None:
            status["health"] = self._monitor.get_health_status()
        if self._supervisor is not None:
            status["supervisor_state"] = self._supervisor.get_state().value
        return status

    def wait_for_shutdown(self) -> None:
        self._shutdown_event.wait()

    def deploy(self) -> bool:
        """Deployment gate alias for start."""

        return self.start_agent()

    def _register_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except ValueError:
            return

    def _signal_handler(self, signum, frame) -> None:  # type: ignore[no-untyped-def]
        del frame
        self._logger.info("Received signal %s, shutting down agent %s", signum, self.config.name)
        self.stop_agent()


def create_agent(config: AgentConfig) -> AgentController:
    """Factory helper for controller creation."""

    return AgentController(config)
