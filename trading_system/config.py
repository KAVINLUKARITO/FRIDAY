from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    mode: Literal["paper", "live"] = "paper"
    log_level: str = "INFO"
    db_path: Path = Path("runtime/trading.db")
    state_path: Path = Path("runtime/state.json")
    log_path: Path = Path("runtime/trading.log")

    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    base_prices: dict[str, float] = Field(
        default_factory=lambda: {"BTCUSDT": 45000.0, "ETHUSDT": 2500.0}
    )

    poll_interval_seconds: float = 5.0
    bar_history_size: int = 100
    simulated_volatility_pct: float = 0.01

    strategy_name: str = "ma_crossover"
    ma_short: int = 5
    ma_long: int = 20

    initial_balance: float = 10000.0
    max_risk_per_trade_pct: float = 0.01
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04
    max_open_trades: int = 3
    max_daily_loss_pct: float = 0.05
    min_order_qty: float = 0.0001
    order_timeout_seconds: float = 30.0

    max_order_retries: int = 3
    retry_backoff_seconds: float = 1.0
    slippage_pct: float = 0.001

    monitor_interval_seconds: float = 10.0
    max_bar_age_seconds: float = 30.0
    alert_email: str = ""

    exchange_id: str = "binance"
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("log_level must not be empty")
        return normalized

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, value: list[str]) -> list[str]:
        symbols = [item.strip().upper() for item in value if item.strip()]
        if not symbols:
            raise ValueError("symbols must not be empty")
        return symbols

    @field_validator(
        "poll_interval_seconds",
        "simulated_volatility_pct",
        "initial_balance",
        "max_risk_per_trade_pct",
        "stop_loss_pct",
        "take_profit_pct",
        "max_daily_loss_pct",
        "min_order_qty",
        "order_timeout_seconds",
        "retry_backoff_seconds",
        "slippage_pct",
        "monitor_interval_seconds",
        "max_bar_age_seconds",
    )
    @classmethod
    def validate_positive_float(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value

    @field_validator("bar_history_size", "ma_short", "ma_long", "max_open_trades", "max_order_retries")
    @classmethod
    def validate_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value


settings = Settings()
