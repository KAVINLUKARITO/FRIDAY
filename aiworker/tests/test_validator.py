from __future__ import annotations

import pytest

from validator import ValidatedAction, ValidationError, Validator


@pytest.fixture()
def validator_instance() -> Validator:
    return Validator()


def test_valid_action_returns_validated_action(validator_instance: Validator) -> None:
    action = validator_instance.validate(
        {
            "tool_name": "list_files",
            "parameters": {"path": "."},
            "reason": "List files",
            "step_number": 1,
            "agent_name": "TestAgent",
        }
    )
    assert isinstance(action, ValidatedAction)


def test_unknown_tool_raises_validation_error(validator_instance: Validator) -> None:
    with pytest.raises(ValidationError):
        validator_instance.validate(
            {
                "tool_name": "missing",
                "parameters": {"path": "."},
                "reason": "bad",
                "step_number": 1,
                "agent_name": "TestAgent",
            }
        )


def test_empty_parameters_raises_validation_error(validator_instance: Validator) -> None:
    with pytest.raises(ValidationError):
        validator_instance.validate(
            {
                "tool_name": "list_files",
                "parameters": {},
                "reason": "bad",
                "step_number": 1,
                "agent_name": "TestAgent",
            }
        )


def test_step_number_zero_raises_validation_error(validator_instance: Validator) -> None:
    with pytest.raises(ValidationError):
        validator_instance.validate(
            {
                "tool_name": "list_files",
                "parameters": {"path": "."},
                "reason": "bad",
                "step_number": 0,
                "agent_name": "TestAgent",
            }
        )


def test_empty_reason_raises_validation_error(validator_instance: Validator) -> None:
    with pytest.raises(ValidationError):
        validator_instance.validate(
            {
                "tool_name": "list_files",
                "parameters": {"path": "."},
                "reason": "   ",
                "step_number": 1,
                "agent_name": "TestAgent",
            }
        )


def test_empty_agent_name_raises_validation_error(validator_instance: Validator) -> None:
    with pytest.raises(ValidationError):
        validator_instance.validate(
            {
                "tool_name": "list_files",
                "parameters": {"path": "."},
                "reason": "List files",
                "step_number": 1,
                "agent_name": " ",
            }
        )


def test_checksum_deterministic_for_same_input(validator_instance: Validator) -> None:
    raw = {
        "tool_name": "write_file",
        "parameters": {"path": "out.txt", "content": "value"},
        "reason": "Write",
        "step_number": 1,
        "agent_name": "TestAgent",
    }
    first = validator_instance.validate(raw)
    second = validator_instance.validate(raw)
    assert first.checksum == second.checksum


def test_checksum_differs_for_different_params(validator_instance: Validator) -> None:
    first = validator_instance.validate(
        {
            "tool_name": "write_file",
            "parameters": {"path": "a.txt", "content": "one"},
            "reason": "Write",
            "step_number": 1,
            "agent_name": "TestAgent",
        }
    )
    second = validator_instance.validate(
        {
            "tool_name": "write_file",
            "parameters": {"path": "a.txt", "content": "two"},
            "reason": "Write",
            "step_number": 1,
            "agent_name": "TestAgent",
        }
    )
    assert first.checksum != second.checksum
