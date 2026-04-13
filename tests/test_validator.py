from __future__ import annotations

import pytest

from validator import ValidatedAction, ValidationError, Validator


@pytest.fixture()
def validator_instance() -> Validator:
    return Validator()


def test_valid_action_dict_returns_validated_action(validator_instance: Validator) -> None:
    raw = {
        "tool_name": "list_files",
        "parameters": {"path": "."},
        "reason": "List files",
        "step_number": 1,
    }

    result = validator_instance.validate(raw)

    assert isinstance(result, ValidatedAction)
    assert result.tool_name == "list_files"


def test_unknown_tool_name_raises_validation_error(validator_instance: Validator) -> None:
    with pytest.raises(ValidationError):
        validator_instance.validate(
            {
                "tool_name": "unknown_tool",
                "parameters": {"path": "."},
                "reason": "bad",
                "step_number": 1,
            }
        )


def test_missing_tool_name_raises_validation_error(validator_instance: Validator) -> None:
    with pytest.raises(ValidationError):
        validator_instance.validate(
            {
                "parameters": {"path": "."},
                "reason": "bad",
                "step_number": 1,
            }
        )


def test_empty_parameters_dict_raises_validation_error(validator_instance: Validator) -> None:
    with pytest.raises(ValidationError):
        validator_instance.validate(
            {
                "tool_name": "list_files",
                "parameters": {},
                "reason": "bad",
                "step_number": 1,
            }
        )


def test_non_string_reason_raises_validation_error(validator_instance: Validator) -> None:
    with pytest.raises(ValidationError):
        validator_instance.validate(
            {
                "tool_name": "list_files",
                "parameters": {"path": "."},
                "reason": 123,
                "step_number": 1,
            }
        )


def test_step_number_of_zero_raises_validation_error(validator_instance: Validator) -> None:
    with pytest.raises(ValidationError):
        validator_instance.validate(
            {
                "tool_name": "list_files",
                "parameters": {"path": "."},
                "reason": "bad",
                "step_number": 0,
            }
        )


def test_checksum_is_identical_for_identical_inputs(validator_instance: Validator) -> None:
    raw = {
        "tool_name": "write_file",
        "parameters": {"path": "a.txt", "content": "value"},
        "reason": "Write file",
        "step_number": 1,
    }

    first = validator_instance.validate(raw)
    second = validator_instance.validate(raw)

    assert first.checksum == second.checksum


def test_checksum_differs_for_different_parameters(validator_instance: Validator) -> None:
    first = validator_instance.validate(
        {
            "tool_name": "write_file",
            "parameters": {"path": "a.txt", "content": "one"},
            "reason": "Write file",
            "step_number": 1,
        }
    )
    second = validator_instance.validate(
        {
            "tool_name": "write_file",
            "parameters": {"path": "a.txt", "content": "two"},
            "reason": "Write file",
            "step_number": 1,
        }
    )

    assert first.checksum != second.checksum
