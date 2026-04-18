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
        checksum="abc123",
    )


def test_valid_validated_action_executes_and_returns_execution_result(
    monkeypatch: pytest.MonkeyPatch,
    validated_action: ValidatedAction,
) -> None:
    monkeypatch.setitem(executor.TOOL_REGISTRY, "list_files", lambda path: ["a.txt"])

    result = Executor().run(validated_action)

    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert result.output == ["a.txt"]


def test_passing_raw_dict_raises_type_error() -> None:
    with pytest.raises(TypeError):
        Executor().run({"tool_name": "list_files"})  # type: ignore[arg-type]


def test_tool_raises_tool_error_returns_failed_result(
    monkeypatch: pytest.MonkeyPatch,
    validated_action: ValidatedAction,
) -> None:
    def failing_tool(path: str) -> list[str]:
        raise ToolError(f"bad path: {path}")

    monkeypatch.setitem(executor.TOOL_REGISTRY, "list_files", failing_tool)

    result = Executor().run(validated_action)

    assert result.success is False
    assert "bad path" in (result.error or "")


def test_tool_raises_safety_error_returns_failed_result(
    monkeypatch: pytest.MonkeyPatch,
    validated_action: ValidatedAction,
) -> None:
    def failing_tool(path: str) -> list[str]:
        raise SafetyError(f"unsafe path: {path}")

    monkeypatch.setitem(executor.TOOL_REGISTRY, "list_files", failing_tool)

    result = Executor().run(validated_action)

    assert result.success is False
    assert "unsafe path" in (result.error or "")


def test_duration_seconds_is_positive_float(
    monkeypatch: pytest.MonkeyPatch,
    validated_action: ValidatedAction,
) -> None:
    monkeypatch.setitem(executor.TOOL_REGISTRY, "list_files", lambda path: ["a.txt"])

    result = Executor().run(validated_action)

    assert isinstance(result.duration_seconds, float)
    assert result.duration_seconds >= 0.0


def test_timed_out_is_false_on_normal_execution(
    monkeypatch: pytest.MonkeyPatch,
    validated_action: ValidatedAction,
) -> None:
    monkeypatch.setitem(executor.TOOL_REGISTRY, "list_files", lambda path: ["a.txt"])

    result = Executor().run(validated_action)

    assert result.timed_out is False


def test_read_file_requires_non_empty_path_parameter() -> None:
    action = ValidatedAction(
        tool_name="read_file",
        parameters={},
        reason="Read file",
        step_number=1,
        checksum="abc123",
    )

    with pytest.raises(ToolError, match="read_file requires a non-empty 'path' parameter"):
        Executor().run(action)


def test_read_file_fails_when_tool_returns_empty_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = ValidatedAction(
        tool_name="read_file",
        parameters={"path": "sample.txt"},
        reason="Read file",
        step_number=1,
        checksum="abc123",
    )
    monkeypatch.setitem(executor.TOOL_REGISTRY, "read_file", lambda path: "")

    with pytest.raises(ToolError, match="read_file returned empty content"):
        Executor().run(action)
