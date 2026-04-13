from aiworker.os.models import CommandRequest, CommandResult
from aiworker.os.policy import CommandPolicy
from aiworker.os.sandbox import SafeSubprocessRunner
from aiworker.safety.runtime_guard import RuntimeGuard


class LinuxExecutor:

    def __init__(
        self,
        policy: CommandPolicy,
        guard: RuntimeGuard,
        runner: SafeSubprocessRunner,
    ) -> None:
        self._policy: CommandPolicy = policy
        self._guard: RuntimeGuard = guard
        self._runner: SafeSubprocessRunner = runner

    def execute(self, request: CommandRequest) -> CommandResult:
        self._policy.validate(request)
        self._guard.inspect(request)
        return self._runner.run(request)
