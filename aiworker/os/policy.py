from aiworker.core.exceptions import PolicyViolationError
from aiworker.os.models import CommandRequest

_MAX_COMMAND_LENGTH: int = 500

_BLOCKED_COMMANDS: tuple[str, ...] = (
    "rm -rf /",
    "shutdown",
    "reboot",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
)

_BLOCKED_SUBSTRINGS: tuple[str, ...] = (
    "/dev/sd",
    "sudo",
)


class CommandPolicy:

    def validate(self, request: CommandRequest) -> None:
        cmd: str = request.command

        if len(cmd) > _MAX_COMMAND_LENGTH:
            raise PolicyViolationError(
                f"Command exceeds maximum length of {_MAX_COMMAND_LENGTH} characters"
            )

        if not cmd.isascii():
            raise PolicyViolationError("Command contains non-ASCII characters")

        cmd_lower: str = cmd.lower().strip()

        for blocked in _BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                raise PolicyViolationError(
                    f"Blocked dangerous command pattern: {blocked!r}"
                )

        for substring in _BLOCKED_SUBSTRINGS:
            if substring in cmd_lower:
                raise PolicyViolationError(
                    f"Blocked dangerous substring: {substring!r}"
                )
