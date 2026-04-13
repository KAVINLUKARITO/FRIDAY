import shlex
import subprocess
import time

from aiworker.core.exceptions import ExecutionTimeoutError
from aiworker.core.types import ExitCode
from aiworker.os.models import CommandRequest, CommandResult


class SafeSubprocessRunner:

    def run(self, request: CommandRequest) -> CommandResult:
        args: list[str] = shlex.split(request.command)

        start: float = time.monotonic()
        try:
            proc: subprocess.CompletedProcess[str] = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=request.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed: float = time.monotonic() - start
            raise ExecutionTimeoutError(
                f"Command timed out after {elapsed:.2f}s "
                f"(limit: {request.timeout}s)"
            ) from exc

        elapsed = time.monotonic() - start

        return CommandResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=ExitCode(proc.returncode),
            execution_time=round(elapsed, 4),
            blocked=False,
        )
