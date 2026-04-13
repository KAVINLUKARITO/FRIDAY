from __future__ import annotations

import asyncio
import signal

from config import settings
from data_engine import DataEngine
from execution_engine import ExecutionEngine
from logger import get_logger
from models import BarData, Signal
from monitor import Monitor
from portfolio_manager import PortfolioManager
from risk_manager import KillSwitch, RiskManager
from storage import Storage
from strategy_engine import StrategyEngine


class TradingSystem:
    def __init__(self) -> None:
        self.logger = get_logger("trading_system")
        self.storage = Storage(settings.db_path)
        self.portfolio_manager = PortfolioManager(self.storage)
        self.kill_switch = KillSwitch()
        self.risk_manager = RiskManager(self.storage, self.kill_switch)
        self.execution_engine = ExecutionEngine(self.storage, self.kill_switch)
        self.strategy_engine = StrategyEngine(self.storage)
        self.data_engine = DataEngine(self.storage, self._on_bar)
        self.monitor = Monitor(
            self.storage,
            self.data_engine,
            self.portfolio_manager,
            self.kill_switch,
        )
        self._shutdown_started = False

    async def start(self) -> None:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage.init_db()
        self.portfolio_manager.load_state()
        self.logger.info(
            "system starting run_id=%s mode=%s symbols=%s",
            settings.run_id,
            settings.mode,
            ",".join(settings.symbols),
        )
        self._register_signal_handlers()
        await asyncio.gather(self.data_engine.start(), self.monitor.start())

    async def _on_bar(self, bar: BarData) -> None:
        try:
            self.portfolio_manager.update_prices(bar.symbol, bar.close)
            for position in list(self.portfolio_manager.get_open_positions()):
                if position.symbol != bar.symbol:
                    continue
                exit_reason = self.risk_manager.check_exit_conditions(position, bar.close)
                if exit_reason is None:
                    continue
                order = await self.execution_engine.close_position(position, bar.close, exit_reason)
                if order.status.value == "FILLED" and order.fill_price is not None:
                    self.portfolio_manager.on_position_closed(position, order.fill_price, exit_reason)

            await self.strategy_engine.on_bar(bar, self._on_signal)
        except Exception as exc:
            self.logger.exception("bar handling failed for %s: %s", bar.symbol, exc)
            self.kill_switch.activate("unhandled error in bar processing")
            await self.shutdown()

    async def _on_signal(self, signal: Signal) -> None:
        snapshot = self.portfolio_manager.get_snapshot()
        decision = self.risk_manager.evaluate(signal, snapshot)
        if not decision.approved or decision.adjusted_qty is None:
            self.logger.info("signal rejected: %s", decision.reason)
            return
        order = await self.execution_engine.place_order(signal, decision.adjusted_qty)
        if order.status.value == "FILLED":
            trade = self.portfolio_manager.on_order_filled(order)
            self.logger.info(
                "trade opened: %s %s %s @ %.6f",
                trade.trade_id,
                order.symbol,
                order.side,
                order.fill_price if order.fill_price is not None else order.entry_price,
            )
        else:
            self.logger.info("order not filled: %s %s", order.order_id, order.status.value)

    async def shutdown(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        self.logger.info("shutdown initiated")
        self.data_engine.stop()
        self.monitor.stop()
        self.portfolio_manager.save_state()
        final_snapshot = self.portfolio_manager.get_snapshot()
        self.logger.info("final portfolio snapshot: %s", final_snapshot.model_dump_json())
        self.storage.close()
        self.logger.info("shutdown complete")

    def _register_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()

        def _handler() -> None:
            loop.create_task(self.shutdown())

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _handler)
            except (NotImplementedError, RuntimeError):
                signal.signal(sig, lambda *_args: loop.create_task(self.shutdown()))


if __name__ == "__main__":
    system = TradingSystem()
    try:
        asyncio.run(system.start())
    except KeyboardInterrupt:
        pass
