from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    workspace_dir: Path = Path("workspace")
    db_path: Path = Path("runtime/history.db")
    log_level: str = "INFO"

    max_steps: int = 20
    max_retries: int = 3
    max_replans: int = 2
    retry_backoff_base: float = 1.0
    step_timeout: float = 30.0

    http_timeout: float = 10.0

    bug_bounty_target: str = "http://localhost:8080"
    safe_test_mode: bool = True

    trading_mode: str = "paper"
    trading_symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    poll_interval_seconds: float = 5.0
    initial_balance: float = 10000.0
    max_position_pct: float = 0.10
    stop_loss_pct: float = 0.02
    ma_short: int = 5
    ma_long: int = 20

    binance_api_key: str = ""
    binance_api_secret: str = ""
    zerodha_api_key: str = ""
    zerodha_access_token: str = ""

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("log_level must not be empty")
        return normalized

    @field_validator("max_steps", "max_retries", "max_replans", "ma_short", "ma_long")
    @classmethod
    def validate_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value

    @field_validator(
        "retry_backoff_base",
        "step_timeout",
        "http_timeout",
        "poll_interval_seconds",
        "initial_balance",
        "max_position_pct",
        "stop_loss_pct",
    )
    @classmethod
    def validate_positive_numbers(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value

    @field_validator("trading_mode")
    @classmethod
    def validate_trading_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"paper", "live"}:
            raise ValueError("trading_mode must be 'paper' or 'live'")
        return normalized

    @field_validator("trading_symbols")
    @classmethod
    def validate_symbols(cls, value: list[str]) -> list[str]:
        symbols = [symbol.strip().upper() for symbol in value if symbol.strip()]
        if not symbols:
            raise ValueError("trading_symbols must contain at least one symbol")
        return symbols


settings = Settings()
