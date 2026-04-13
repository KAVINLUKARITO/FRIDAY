from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class Settings(BaseModel):
    """Application settings with environment variable overrides."""

    model_config = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True)

    workspace_dir: Path = Path("workspace")
    db_path: Path = Path("runtime/history.db")
    max_steps: int = 20
    max_retries: int = 3
    max_replans: int = 2
    retry_backoff_base: float = 1.0
    http_timeout: float = 10.0
    log_level: str = "INFO"
    planner_mode: str = "echo"

    def __init__(self, **data: Any) -> None:
        merged = self._load_environment_values()
        merged.update(data)
        super().__init__(**merged)

    @staticmethod
    def _load_environment_values() -> dict[str, Any]:
        env_map: dict[str, tuple[str, type[Any]]] = {
            "workspace_dir": ("WORKSPACE_DIR", str),
            "db_path": ("DB_PATH", str),
            "max_steps": ("MAX_STEPS", int),
            "max_retries": ("MAX_RETRIES", int),
            "max_replans": ("MAX_REPLANS", int),
            "retry_backoff_base": ("RETRY_BACKOFF_BASE", float),
            "http_timeout": ("HTTP_TIMEOUT", float),
            "log_level": ("LOG_LEVEL", str),
            "planner_mode": ("PLANNER_MODE", str),
        }
        values: dict[str, Any] = {}
        for field_name, (env_name, caster) in env_map.items():
            raw_value = os.getenv(env_name)
            if raw_value is None:
                continue
            values[field_name] = raw_value if caster is str else caster(raw_value)
        return values

    @field_validator("max_steps", "max_retries", "max_replans")
    @classmethod
    def _validate_non_negative_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be non-negative")
        return value

    @field_validator("retry_backoff_base", "http_timeout")
    @classmethod
    def _validate_positive_float(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("log_level must not be empty")
        return normalized

    @field_validator("planner_mode")
    @classmethod
    def _normalize_planner_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"echo", "llm"}:
            raise ValueError("planner_mode must be 'echo' or 'llm'")
        return normalized


settings = Settings()
