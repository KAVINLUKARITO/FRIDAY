from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from aiworker.pipeline.validator import ValidatedAction

logger = logging.getLogger(__name__)


class VerificationResult(BaseModel):
    status: Literal["SUCCESS", "FAILURE", "UNVERIFIED"]
    reason: str = Field(min_length=1)
    raw_output: Any
    verified_at: datetime


class Verifier:
    def verify(self, action: ValidatedAction, output: Any) -> VerificationResult:
        if output is None or output == {} or output == [] or output == "":
            return self._result("UNVERIFIED", "empty output cannot be verified", output)

        expected = self._expected_shape(action.tool_name)
        if expected and not self._matches_shape(output, expected):
            return self._result("FAILURE", f"output shape does not match expected keys: {sorted(expected)}", output)

        side_effect = self._verify_side_effect(action, output)
        if side_effect is not None:
            return side_effect

        return self._result("SUCCESS", "output shape and side effects verified", output)

    def _verify_side_effect(self, action: ValidatedAction, output: Any) -> VerificationResult | None:
        expected_path = action.parameters.get("expected_path") or action.parameters.get("path_must_exist")
        if expected_path is None:
            return None
        path = Path(str(expected_path)).expanduser().resolve()
        if not path.exists():
            return self._result("UNVERIFIED", f"expected side effect missing: {path}", output)
        return None

    @staticmethod
    def _expected_shape(tool_name: str) -> dict[str, type] | None:
        shapes: dict[str, dict[str, type]] = {
            "echo": {"text": str},
            "list_files": {"files": list},
            "read_file": {"path": str, "content": str},
            "http_get": {"status_code": int, "text": str, "headers": dict},
            "system_info": {"python_version": str, "platform": str, "processor": str},
        }
        return shapes.get(tool_name)

    @staticmethod
    def _matches_shape(output: Any, expected: dict[str, type]) -> bool:
        if not isinstance(output, dict):
            return False
        for key, expected_type in expected.items():
            if key not in output or not isinstance(output[key], expected_type):
                return False
        return True

    @staticmethod
    def _result(status: Literal["SUCCESS", "FAILURE", "UNVERIFIED"], reason: str, output: Any) -> VerificationResult:
        if status != "SUCCESS":
            logger.warning("verification %s: %s", status, reason)
        return VerificationResult(
            status=status,
            reason=reason,
            raw_output=output,
            verified_at=datetime.now(timezone.utc),
        )
