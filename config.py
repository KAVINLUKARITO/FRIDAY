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
    bug_bounty_target: str = "http://localhost:8080"
    safe_test_mode: bool = True
    trading_mode: str = "paper"
    trading_symbols: list[str] = ["BTCUSDT", "ETHUSDT"]
    poll_interval_seconds: float = 5.0
    initial_balance: float = 10000.0
    max_position_pct: float = 0.10
    stop_loss_pct: float = 0.02
    ma_short: int = 5
    ma_long: int = 20
    binance_api_key: str = ""
    binance_api_secret: str = ""

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
            "bug_bounty_target": ("BUG_BOUNTY_TARGET", str),
            "safe_test_mode": ("SAFE_TEST_MODE", str),
            "trading_mode": ("TRADING_MODE", str),
            "poll_interval_seconds": ("POLL_INTERVAL_SECONDS", float),
            "initial_balance": ("INITIAL_BALANCE", float),
            "max_position_pct": ("MAX_POSITION_PCT", float),
            "stop_loss_pct": ("STOP_LOSS_PCT", float),
            "ma_short": ("MA_SHORT", int),
            "ma_long": ("MA_LONG", int),
            "binance_api_key": ("BINANCE_API_KEY", str),
            "binance_api_secret": ("BINANCE_API_SECRET", str),
        }
        values: dict[str, Any] = {}
        for field_name, (env_name, caster) in env_map.items():
            raw_value = os.getenv(env_name)
            if raw_value is None:
                continue
            if field_name == "safe_test_mode":
                values[field_name] = raw_value.lower() in {"1", "true", "yes", "on"}
            else:
                values[field_name] = raw_value if caster is str else caster(raw_value)
        return values

    @field_validator("max_steps", "max_retries", "max_replans", "ma_short", "ma_long")
    @classmethod
    def _validate_non_negative_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be non-negative")
        return value

    @field_validator(
        "retry_backoff_base",
        "http_timeout",
        "poll_interval_seconds",
        "initial_balance",
        "max_position_pct",
        "stop_loss_pct",
    )
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

    @field_validator("trading_mode")
    @classmethod
    def _normalize_trading_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"paper", "live"}:
            raise ValueError("trading_mode must be 'paper' or 'live'")
        return normalized


settings = Settings()
