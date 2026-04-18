from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
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


@dataclass(frozen=True, slots=True)
class AIWorkerConfig:
    base_path: Path = Path(".")
    workspace_path: str = "workspace"
    db_path: Path = Path("runtime/history.db")
    checkpoint_db: Path = Path("runtime/history.db")
    log_level: str = "INFO"

    max_iterations: int = 20
    max_attempts: int = 3
    max_failures: int = 3
    confidence_threshold: float = 0.70
    max_lines_changed: int = 200
    sandbox_timeout: int = 60
    tool_timeout_seconds: float = 30.0

    circuit_breaker_threshold: int = 3
    rate_limit_max: int = 5
    rate_limit_window: int = 60
    health_check_enabled: bool = True
    auto_approve: bool = False

    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3:8b"
    ollama_timeout: int = 300
    ollama_temperature: float = 0.2
    anthropic_model: str = "claude-3-5-sonnet"

    self_modify_forbidden: tuple[str, ...] = field(
        default_factory=lambda: ("aiworker/config.py", ".env", "secrets", "credentials")
    )

    def __post_init__(self) -> None:
        base_path = Path(self.base_path)
        workspace_path = str(self.workspace_path)
        db_path = Path(self.db_path)
        checkpoint_db = Path(self.checkpoint_db)
        log_level = self.log_level.strip().upper()
        if not workspace_path.strip():
            raise ValueError("workspace_path must not be empty")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.max_failures < 1:
            raise ValueError("max_failures must be >= 1")
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        if self.max_lines_changed < 1:
            raise ValueError("max_lines_changed must be >= 1")
        if self.sandbox_timeout < 1:
            raise ValueError("sandbox_timeout must be >= 1")
        if self.tool_timeout_seconds <= 0:
            raise ValueError("tool_timeout_seconds must be > 0")
        if self.ollama_timeout < 1:
            raise ValueError("ollama_timeout must be >= 1")
        object.__setattr__(self, "base_path", base_path)
        object.__setattr__(self, "workspace_path", workspace_path)
        object.__setattr__(self, "db_path", db_path)
        object.__setattr__(self, "checkpoint_db", checkpoint_db)
        object.__setattr__(self, "log_level", log_level)

    @property
    def workspace_dir(self) -> Path:
        return Path(self.workspace_path)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["base_path"] = str(self.base_path)
        data["db_path"] = str(self.db_path)
        data["checkpoint_db"] = str(self.checkpoint_db)
        return data

    @classmethod
    def from_env(cls) -> AIWorkerConfig:
        current = settings
        base_path = Path(os.getenv("AIWORKER_BASE_PATH", "."))
        workspace_path = os.getenv("AIWORKER_WORKSPACE_PATH", str(current.workspace_dir))
        db_path = Path(os.getenv("AIWORKER_DB_PATH", str(current.db_path)))
        checkpoint_db = Path(os.getenv("AIWORKER_CHECKPOINT_DB", str(db_path)))
        return cls(
            base_path=base_path,
            workspace_path=workspace_path,
            db_path=db_path,
            checkpoint_db=checkpoint_db,
            log_level=os.getenv("AIWORKER_LOG_LEVEL", current.log_level),
            max_iterations=int(os.getenv("AIWORKER_MAX_ITERATIONS", str(current.max_steps))),
            max_attempts=int(os.getenv("AIWORKER_MAX_ATTEMPTS", "3")),
            max_failures=int(os.getenv("AIWORKER_MAX_FAILURES", "3")),
            confidence_threshold=float(os.getenv("AIWORKER_CONFIDENCE_THRESHOLD", "0.70")),
            max_lines_changed=int(os.getenv("AIWORKER_MAX_LINES_CHANGED", "200")),
            sandbox_timeout=int(os.getenv("AIWORKER_SANDBOX_TIMEOUT", "60")),
            tool_timeout_seconds=float(os.getenv("AIWORKER_TOOL_TIMEOUT_SECONDS", str(current.step_timeout))),
            circuit_breaker_threshold=int(os.getenv("AIWORKER_CIRCUIT_BREAKER_THRESHOLD", "3")),
            rate_limit_max=int(os.getenv("AIWORKER_RATE_LIMIT_MAX", "5")),
            rate_limit_window=int(os.getenv("AIWORKER_RATE_LIMIT_WINDOW", "60")),
            health_check_enabled=os.getenv("AIWORKER_HEALTH_CHECK_ENABLED", "true").lower() not in {"0", "false", "no"},
            auto_approve=os.getenv("AIWORKER_AUTO_APPROVE", "false").lower() in {"1", "true", "yes"},
            ollama_host=os.getenv("AIWORKER_OLLAMA_HOST", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("AIWORKER_OLLAMA_MODEL", "llama3:8b"),
            ollama_timeout=int(os.getenv("AIWORKER_OLLAMA_TIMEOUT", "300")),
            ollama_temperature=float(os.getenv("AIWORKER_OLLAMA_TEMPERATURE", "0.2")),
            anthropic_model=os.getenv("AIWORKER_ANTHROPIC_MODEL", "claude-3-5-sonnet"),
        )


settings = Settings()
