from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Literal


FailureKind = Literal["validation", "execution", "verification", "system", "loop", "timeout"]


class FailureType(str, Enum):
    VALIDATION = "validation"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    SYSTEM = "system"
    LOOP = "loop"
    TIMEOUT = "timeout"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(slots=True)
class ClassifiedFailure:
    type: FailureType
    message: str
    retryable: bool
    source_module: str
    action_id: str | None
    timestamp: float = field(default_factory=time.time)
    raw_exception: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), sort_keys=True)

    @property
    def severity(self) -> Severity:
        if self.type is FailureType.SYSTEM:
            return Severity.CRITICAL
        if self.type is FailureType.TIMEOUT:
            return Severity.HIGH
        if self.type in {FailureType.VALIDATION, FailureType.VERIFICATION, FailureType.LOOP}:
            return Severity.MEDIUM
        return Severity.LOW


Failure = ClassifiedFailure


class FailureClassifier:
    MAX_EXECUTION_RETRIES = 3
    MAX_VERIFICATION_RETRIES = 1
    MAX_TIMEOUT_RETRIES = 1

    @classmethod
    def from_validation(cls, result: Any, action: Any) -> ClassifiedFailure:
        reason = _read_attr(result, "reason") or _read_attr(result, "message") or "validation failed"
        return ClassifiedFailure(
            type=FailureType.VALIDATION,
            message=str(reason),
            retryable=False,
            source_module="validator",
            action_id=_action_id(action),
        )

    @classmethod
    def from_execution(cls, result: Any, action: Any) -> ClassifiedFailure:
        timed_out = bool(_read_attr(result, "timed_out", False))
        failure_type = FailureType.TIMEOUT if timed_out else FailureType.EXECUTION
        message = (
            _read_attr(result, "error")
            or _read_attr(result, "message")
            or ("execution timed out" if timed_out else "execution failed")
        )
        return ClassifiedFailure(
            type=failure_type,
            message=str(message),
            retryable=failure_type in {"execution", "timeout"},
            source_module="executor",
            action_id=_action_id(action) or _read_attr(result, "action_id"),
        )

    @classmethod
    def from_verification(cls, result: Any, action: Any) -> ClassifiedFailure:
        reason = _read_attr(result, "reason") or _read_attr(result, "message") or "verification failed"
        return ClassifiedFailure(
            type=FailureType.VERIFICATION,
            message=str(reason),
            retryable=True,
            source_module="verifier",
            action_id=_action_id(action),
        )

    @classmethod
    def from_exception(cls, exc: Exception, source: str, action_id: str | None) -> ClassifiedFailure:
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            return ClassifiedFailure(
                type=FailureType.TIMEOUT,
                message=str(exc) or "operation timed out",
                retryable=True,
                source_module=source,
                action_id=action_id,
                raw_exception=str(exc),
            )
        return ClassifiedFailure(
            type=FailureType.SYSTEM,
            message=str(exc) or exc.__class__.__name__,
            retryable=False,
            source_module=source,
            action_id=action_id,
            raw_exception=str(exc),
        )

    @classmethod
    def is_retryable(cls, failure: ClassifiedFailure) -> bool:
        return failure.retryable

    @classmethod
    def retry_limit_for(cls, failure: ClassifiedFailure) -> int:
        if failure.type is FailureType.EXECUTION:
            return cls.MAX_EXECUTION_RETRIES
        if failure.type is FailureType.VERIFICATION:
            return cls.MAX_VERIFICATION_RETRIES
        if failure.type is FailureType.TIMEOUT:
            return cls.MAX_TIMEOUT_RETRIES
        return 0

    @classmethod
    def classify_validation_error(cls, message: str, context: dict[str, Any]) -> ClassifiedFailure:
        action_id = _context_action_id(context)
        return ClassifiedFailure(
            type=FailureType.VALIDATION,
            message=message,
            retryable=False,
            source_module="validator",
            action_id=action_id,
        )

    @classmethod
    def classify_execution_error(
        cls,
        exc: Exception,
        context: dict[str, Any],
        retryable: bool = True,
    ) -> ClassifiedFailure:
        failure = cls.from_exception(exc, "executor", _context_action_id(context))
        if failure.type is FailureType.SYSTEM:
            failure = ClassifiedFailure(
                type=FailureType.EXECUTION,
                message=failure.message,
                retryable=retryable,
                source_module="executor",
                action_id=failure.action_id,
                raw_exception=failure.raw_exception,
            )
        return failure

    @classmethod
    def classify_verification_error(cls, message: str, context: dict[str, Any]) -> ClassifiedFailure:
        return ClassifiedFailure(
            type=FailureType.VERIFICATION,
            message=message,
            retryable=True,
            source_module="verifier",
            action_id=_context_action_id(context),
        )

    @classmethod
    def classify_system_error(cls, exc: Exception, context: dict[str, Any]) -> ClassifiedFailure:
        return cls.from_exception(exc, "supervisor", _context_action_id(context))


_DEFAULT_CLASSIFIER = FailureClassifier()
_failure_handlers: list[Callable[[ClassifiedFailure], None]] = []


def register_failure_handler(handler: Callable[[ClassifiedFailure], None]) -> None:
    _failure_handlers.append(handler)


def clear_failure_handlers() -> None:
    _failure_handlers.clear()


def report_failure(failure: ClassifiedFailure) -> None:
    for handler in list(_failure_handlers):
        handler(failure)


def capture_exception_trace(exc: Exception) -> str | None:
    stack_trace = traceback.format_exc()
    if stack_trace.strip() == "NoneType: None":
        return str(exc) if str(exc) else None
    return stack_trace


def _read_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _action_id(action: Any) -> str | None:
    if action is None:
        return None
    if isinstance(action, dict):
        action_id = action.get("id") or action.get("action_id")
        if action_id is not None:
            return str(action_id)
        return None
    action_id = getattr(action, "id", None) or getattr(action, "action_id", None)
    return None if action_id is None else str(action_id)


def _context_action_id(context: dict[str, Any]) -> str | None:
    action = context.get("action")
    return _action_id(action) or context.get("action_id")


__all__ = [
    "ClassifiedFailure",
    "Failure",
    "FailureClassifier",
    "FailureType",
    "Severity",
    "capture_exception_trace",
    "clear_failure_handlers",
    "register_failure_handler",
    "report_failure",
]
