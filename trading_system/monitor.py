from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from threading import Event

from config import settings
from data_engine import DataEngine
from logger import get_logger
from models import HealthStatus
from portfolio_manager import PortfolioManager
from risk_manager import KillSwitch
from storage import Storage


class Monitor:
    def __init__(
        self,
        storage: Storage,
        data_engine: DataEngine,
        portfolio_manager: PortfolioManager,
        kill_switch: KillSwitch,
    ) -> None:
        self.storage = storage
        self.data_engine = data_engine
        self.portfolio_manager = portfolio_manager
        self.kill_switch = kill_switch
        self.logger = get_logger("monitor")
        self._shutdown_event = Event()

    async def start(self) -> None:
        while not self._shutdown_event.is_set():
            self.health_check()
            await asyncio.sleep(settings.monitor_interval_seconds)

    def stop(self) -> None:
        self._shutdown_event.set()

    def health_check(self) -> HealthStatus:
        alerts: list[str] = []
        storage_ok = True
        try:
            self.storage.ping()
        except Exception as exc:
            storage_ok = False
            alerts.append(f"storage check failed: {exc}")

        ages = [self.data_engine.get_last_bar_age(symbol) for symbol in settings.symbols]
        worst_age = max(ages) if ages else float("inf")
        data_feed_ok = all(age < settings.max_bar_age_seconds for age in ages) if ages else False
        if not data_feed_ok:
            alerts.append("data feed lag exceeds threshold")

        daily_loss_limit = settings.initial_balance * settings.max_daily_loss_pct
        if self.portfolio_manager.daily_pnl <= -(daily_loss_limit * 0.8):
            alerts.append("daily loss exceeds 80% of configured limit")
            self._send_alert("daily loss exceeds 80% of configured limit")

        status = "HEALTHY"
        if self.kill_switch.is_active() or any(age > settings.max_bar_age_seconds * 3.0 for age in ages):
            status = "CRITICAL"
        elif any(age > settings.max_bar_age_seconds for age in ages) or (
            self.portfolio_manager.daily_pnl <= -(daily_loss_limit * 0.8)
        ):
            status = "DEGRADED"

        snapshot = self.portfolio_manager.get_snapshot()
        try:
            self.storage.save_snapshot(snapshot)
        except Exception as exc:
            storage_ok = False
            alerts.append(f"snapshot save failed: {exc}")

        health = HealthStatus(
            status=status,
            data_feed_ok=data_feed_ok,
            storage_ok=storage_ok,
            kill_switch_active=self.kill_switch.is_active(),
            last_bar_age_seconds=0.0 if worst_age == float("inf") else worst_age,
            open_positions=len(self.portfolio_manager.get_open_positions()),
            daily_pnl=self.portfolio_manager.daily_pnl,
            alerts=alerts,
            checked_at=datetime.now(UTC),
        )

        if status == "CRITICAL":
            self.logger.critical("health status=%s alerts=%s", health.status, alerts)
        elif status == "DEGRADED":
            self.logger.warning("health status=%s alerts=%s", health.status, alerts)
        else:
            self.logger.info("health status=%s", health.status)
        return health

    def _send_alert(self, message: str) -> None:
        self.logger.critical(message)
        if settings.alert_email:
            self.logger.critical("ALERT EMAIL WOULD SEND TO %s: %s", settings.alert_email, message)
