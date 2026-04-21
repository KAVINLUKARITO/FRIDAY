from __future__ import annotations

import os
from pathlib import Path
from typing import Any


_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


def _load_plain(path: str | Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    key, _, value = line.partition(":")
                    value = value.strip().strip('"').strip("'")
                    lowered = value.lower()
                    if lowered in {"true", "false"}:
                        result[key.strip()] = lowered == "true"
                        continue
                    try:
                        result[key.strip()] = int(value)
                    except ValueError:
                        try:
                            result[key.strip()] = float(value)
                        except ValueError:
                            result[key.strip()] = value
    except Exception:
        pass
    return result


try:
    import yaml  # type: ignore

    def _load() -> dict[str, Any]:
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle)
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return _load_plain(_CONFIG_PATH)

except ImportError:

    def _load() -> dict[str, Any]:
        return _load_plain(_CONFIG_PATH)


class Settings:
    """Application settings with environment variable overrides."""

    def __init__(self, **data: Any) -> None:
        defaults: dict[str, Any] = {
            "workspace_dir": Path("workspace"),
            "db_path": Path("runtime/history.db"),
            "max_steps": 20,
            "max_retries": 3,
            "max_replans": 2,
            "retry_backoff_base": 1.0,
            "http_timeout": 10.0,
            "log_level": "INFO",
            "planner_mode": "echo",
            "bug_bounty_target": "http://localhost:8080",
            "safe_test_mode": True,
            "trading_mode": "paper",
            "trading_symbols": ["BTCUSDT", "ETHUSDT"],
            "poll_interval_seconds": 5.0,
            "initial_balance": 10000.0,
            "max_position_pct": 0.10,
            "stop_loss_pct": 0.02,
            "ma_short": 5,
            "ma_long": 20,
            "binance_api_key": "",
            "binance_api_secret": "",
        }
        defaults.update(self._load_environment_values())
        defaults.update(data)
        defaults["workspace_dir"] = Path(defaults["workspace_dir"])
        defaults["db_path"] = Path(defaults["db_path"])
        defaults["log_level"] = str(defaults["log_level"]).strip().upper() or "INFO"
        defaults["planner_mode"] = self._normalize_choice(defaults["planner_mode"], {"echo", "llm"}, "echo")
        defaults["trading_mode"] = self._normalize_choice(defaults["trading_mode"], {"paper", "live"}, "paper")
        for key, value in defaults.items():
            setattr(self, key, value)

    @staticmethod
    def _normalize_choice(value: Any, allowed: set[str], fallback: str) -> str:
        normalized = str(value).strip().lower()
        return normalized if normalized in allowed else fallback

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


settings = Settings()
cfg = _load()
