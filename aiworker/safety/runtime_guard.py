from aiworker.core.exceptions import UnsafeCommandError
from aiworker.os.models import CommandRequest

_MAX_EXECUTION_TIME: int = 5
_MAX_STDOUT_BYTES: int = 1_048_576  # 1 MB

_FORK_BOMB_PATTERNS: tuple[str, ...] = (
    ":(){ :|:& };:",
    ":(){:|:&};:",
    ":()",
    "fork()",
    "while true; do",
    "while :; do",
)


class RuntimeGuard:

    def __init__(
        self,
        max_execution_time: int = _MAX_EXECUTION_TIME,
        max_stdout_bytes: int = _MAX_STDOUT_BYTES,
    ) -> None:
        self._max_execution_time: int = max_execution_time
        self._max_stdout_bytes: int = max_stdout_bytes

    def inspect(self, request: CommandRequest) -> None:
        if request.timeout > self._max_execution_time:
            raise UnsafeCommandError(
                f"Requested timeout {request.timeout}s exceeds maximum "
                f"allowed {self._max_execution_time}s"
            )

        cmd_lower: str = request.command.lower()
        for pattern in _FORK_BOMB_PATTERNS:
            if pattern in cmd_lower:
                raise UnsafeCommandError(
                    f"Suspicious fork bomb pattern detected: {pattern!r}"
                )
