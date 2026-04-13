from __future__ import annotations

import argparse
import asyncio
import json
import math
from datetime import UTC, datetime, timedelta
from statistics import fmean, pstdev
from typing import Any
from uuid import uuid4

from config import settings
from models import BarData, Order, OrderStatus, PortfolioSnapshot, Position, Trade
from risk_manager import KillSwitch, RiskManager
from storage import Storage
from strategy_engine import StrategyEngine


class BacktestEngine:
    def __init__(self, initial_balance: float, symbols: list[str], bars: list[BarData]) -> None:
        self.initial_balance = initial_balance
        self.symbols = symbols
        self.bars = sorted(bars, key=lambda item: item.timestamp)

    def run(self, strategy: StrategyEngine, risk_mgr: RiskManager) -> dict[str, Any]:
        results = asyncio.run(self._run_async(strategy, risk_mgr))
        metrics = self.compute_metrics(results["trades"], results["equity_curve"], self.initial_balance)
        return {"trades": results["trades"], "equity_curve": results["equity_curve"], "metrics": metrics}

    async def _run_async(self, strategy: StrategyEngine, risk_mgr: RiskManager) -> dict[str, Any]:
        start_ts = self.bars[0].timestamp if self.bars else datetime.now(UTC)
        portfolio = PortfolioSnapshot(
            snapshot_id=str(uuid4()),
            run_id=settings.run_id,
            balance=self.initial_balance,
            equity=self.initial_balance,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            open_positions=0,
            daily_pnl=0.0,
            daily_loss_limit_used_pct=0.0,
            timestamp=start_ts,
        )
        open_positions: dict[str, Position] = {}
        trades: list[Trade] = []
        trade_lookup: dict[str, Trade] = {}
        equity_curve: list[float] = [self.initial_balance]

        async def on_signal(signal: Any) -> None:
            nonlocal portfolio
            decision = risk_mgr.evaluate(signal, portfolio)
            if not decision.approved or decision.adjusted_qty is None:
                return
            order = Order(
                order_id=str(uuid4()),
                client_order_id=str(uuid4()),
                symbol=signal.symbol,
                side=signal.side,
                qty=decision.adjusted_qty,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                status=OrderStatus.FILLED,
                fill_price=signal.entry_price,
                filled_at=signal.timestamp,
                strategy_name=signal.strategy_name,
                run_id=settings.run_id,
                created_at=signal.timestamp,
                updated_at=signal.timestamp,
            )
            trade = Trade(
                trade_id=str(uuid4()),
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                entry_price=order.fill_price or order.entry_price,
                status="OPEN",
                strategy_name=order.strategy_name,
                opened_at=signal.timestamp,
                run_id=settings.run_id,
            )
            trades.append(trade)
            trade_lookup[trade.trade_id] = trade
            if order.side == "BUY":
                portfolio.balance -= order.qty * (order.fill_price or order.entry_price)
                pos_side = "LONG"
            else:
                portfolio.balance += order.qty * (order.fill_price or order.entry_price)
                pos_side = "SHORT"
            open_positions[order.symbol] = Position(
                position_id=trade.trade_id,
                symbol=order.symbol,
                side=pos_side,
                qty=order.qty,
                entry_price=order.fill_price or order.entry_price,
                current_price=order.fill_price or order.entry_price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                unrealized_pnl=0.0,
                opened_at=signal.timestamp,
                order_id=order.order_id,
            )
            portfolio.open_positions = len(open_positions)

        for bar in self.bars:
            position = open_positions.get(bar.symbol)
            if position is not None:
                position.current_price = bar.close
                if position.side == "LONG":
                    position.unrealized_pnl = (bar.close - position.entry_price) * position.qty
                else:
                    position.unrealized_pnl = (position.entry_price - bar.close) * position.qty
                exit_reason = risk_mgr.check_exit_conditions(position, bar.close)
                if exit_reason is not None:
                    trade = trade_lookup[position.position_id]
                    if position.side == "LONG":
                        pnl = (bar.close - position.entry_price) * position.qty
                        portfolio.balance += position.qty * bar.close
                    else:
                        pnl = (position.entry_price - bar.close) * position.qty
                        portfolio.balance -= position.qty * bar.close
                    trade.exit_price = bar.close
                    trade.pnl = pnl
                    trade.status = "CLOSED"
                    trade.closed_at = bar.timestamp
                    portfolio.realized_pnl += pnl
                    portfolio.daily_pnl += pnl
                    open_positions.pop(bar.symbol, None)
                    portfolio.open_positions = len(open_positions)

            portfolio.unrealized_pnl = sum(pos.unrealized_pnl for pos in open_positions.values())
            portfolio.equity = portfolio.balance + portfolio.unrealized_pnl
            portfolio.timestamp = bar.timestamp
            portfolio.daily_loss_limit_used_pct = abs(min(portfolio.daily_pnl, 0.0)) / (
                settings.initial_balance * settings.max_daily_loss_pct
            )
            equity_curve.append(portfolio.equity)
            await strategy.on_bar(bar, on_signal)

        return {"trades": trades, "equity_curve": equity_curve}

    def compute_metrics(self, trades: list[Trade], equity_curve: list[float], initial_balance: float) -> dict[str, Any]:
        closed_trades = [trade for trade in trades if trade.status == "CLOSED" and trade.pnl is not None]
        pnls = [float(trade.pnl) for trade in closed_trades]
        winning = [pnl for pnl in pnls if pnl > 0]
        losing = [pnl for pnl in pnls if pnl < 0]
        gross_profit = sum(winning)
        gross_loss = sum(losing)
        total_pnl = sum(pnls)
        returns = []
        for previous, current in zip(equity_curve, equity_curve[1:]):
            if previous != 0:
                returns.append((current - previous) / previous)
        sharpe_ratio = 0.0
        if returns:
            std_dev = pstdev(returns)
            if std_dev > 0:
                sharpe_ratio = (fmean(returns) / std_dev) * math.sqrt(252)

        peak = equity_curve[0] if equity_curve else initial_balance
        max_drawdown_pct = 0.0
        for equity in equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown_pct = max(max_drawdown_pct, (peak - equity) / peak)

        durations = [
            (trade.closed_at - trade.opened_at).total_seconds()
            for trade in closed_trades
            if trade.closed_at is not None
        ]
        final_balance = equity_curve[-1] if equity_curve else initial_balance

        return {
            "total_trades": len(closed_trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": (len(winning) / len(closed_trades)) if closed_trades else 0.0,
            "total_pnl": total_pnl,
            "total_return_pct": ((final_balance - initial_balance) / initial_balance) if initial_balance else 0.0,
            "avg_win": (sum(winning) / len(winning)) if winning else 0.0,
            "avg_loss": (sum(losing) / len(losing)) if losing else 0.0,
            "profit_factor": (gross_profit / abs(gross_loss)) if gross_loss < 0 else 0.0,
            "max_drawdown_pct": max_drawdown_pct,
            "sharpe_ratio": sharpe_ratio,
            "best_trade_pnl": max(pnls) if pnls else 0.0,
            "worst_trade_pnl": min(pnls) if pnls else 0.0,
            "avg_trade_duration_seconds": (sum(durations) / len(durations)) if durations else 0.0,
            "final_balance": final_balance,
        }

    def generate_report(self, metrics: dict[str, Any], run_id: str) -> None:
        output = settings.db_path.parent / f"backtest_{run_id}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
        print("| Metric | Value |")
        print("| --- | --- |")
        for key, value in metrics.items():
            print(f"| {key} | {value} |")


def _generate_bars(symbols: list[str], bars_per_symbol: int) -> list[BarData]:
    generated: list[BarData] = []
    for symbol in symbols:
        base = settings.base_prices.get(symbol, 100.0)
        start_time = datetime.now(UTC) - timedelta(days=bars_per_symbol)
        for index in range(bars_per_symbol):
            drift = 0.001 * index if index < bars_per_symbol // 2 else -0.001 * (index - (bars_per_symbol // 2))
            close = base * (1.0 + drift)
            generated.append(
                BarData(
                    symbol=symbol,
                    timestamp=start_time + timedelta(days=index),
                    open=round(close * 0.999, 6),
                    high=round(close * 1.002, 6),
                    low=round(close * 0.998, 6),
                    close=round(close, 6),
                    volume=1000.0 + index,
                    simulated=True,
                )
            )
    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the trading system backtest.")
    parser.add_argument("--bars", type=int, default=500)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT"])
    parser.add_argument("--balance", type=float, default=10000.0)
    args = parser.parse_args()

    runtime_db = settings.db_path.parent / "backtest.db"
    storage = Storage(runtime_db)
    storage.init_db()
    strategy = StrategyEngine(storage)
    risk_mgr = RiskManager(storage, KillSwitch())

    bars = _generate_bars(args.symbols, args.bars)
    engine = BacktestEngine(args.balance, args.symbols, bars)
    results = engine.run(strategy, risk_mgr)
    engine.generate_report(results["metrics"], settings.run_id)
    storage.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
