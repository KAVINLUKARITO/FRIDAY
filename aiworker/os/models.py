from dataclasses import dataclass

from aiworker.core.types import CommandString, ExitCode


@dataclass(frozen=True)
class CommandRequest:
    command: CommandString
    timeout: int
    user_context: str


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    exit_code: ExitCode
    execution_time: float
    blocked: bool
