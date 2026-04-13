from __future__ import annotations

import pytest

import executor
from executor import ExecutionResult, Executor
from tools import SafetyError, ToolError
from validator import ValidatedAction


@pytest.fixture()
def validated_action() -> ValidatedAction:
    return ValidatedAction(
        tool_name="list_files",
        parameters={"path": "."},
        reason="List files",
        step_number=1,
        agent_name="TestAgent",
        checksum="checksum",
    )


def test_validated_action_executes_and_returns_execution_result(
    monkeypatch: pytest.MonkeyPatch,
    validated_action: ValidatedAction,
) -> None:
    monkeypatch.setitem(executor.TOOL_REGISTRY, "list_files", lambda path: ["a.txt"])
    result = Executor().run(validated_action)
    assert isinstance(result, ExecutionResult)
    assert result.success is True


def test_raw_dict_raises_type_error() -> None:
    with pytest.raises(TypeError):
        Executor().run({"tool_name": "list_files"})  # type: ignore[arg-type]


def test_tool_error_returns_failed_execution_result(
    monkeypatch: pytest.MonkeyPatch,
    validated_action: ValidatedAction,
) -> None:
    def failing_tool(path: str) -> list[str]:
        raise ToolError("tool failed")

    monkeypatch.setitem(executor.TOOL_REGISTRY, "list_files", failing_tool)
    result = Executor().run(validated_action)
    assert result.success is False
    assert result.error == "tool failed"


def test_safety_error_returns_failed_execution_result(
    monkeypatch: pytest.MonkeyPatch,
    validated_action: ValidatedAction,
) -> None:
    def failing_tool(path: str) -> list[str]:
        raise SafetyError("unsafe")

    monkeypatch.setitem(executor.TOOL_REGISTRY, "list_files", failing_tool)
    result = Executor().run(validated_action)
    assert result.success is False
    assert result.error == "unsafe"


def test_duration_seconds_is_positive_float(
    monkeypatch: pytest.MonkeyPatch,
    validated_action: ValidatedAction,
) -> None:
    monkeypatch.setitem(executor.TOOL_REGISTRY, "list_files", lambda path: ["a.txt"])
    result = Executor().run(validated_action)
    assert isinstance(result.duration_seconds, float)
    assert result.duration_seconds >= 0.0


def test_timed_out_false_on_normal_execution(
    monkeypatch: pytest.MonkeyPatch,
    validated_action: ValidatedAction,
) -> None:
    monkeypatch.setitem(executor.TOOL_REGISTRY, "list_files", lambda path: ["a.txt"])
    result = Executor().run(validated_action)
    assert result.timed_out is False
