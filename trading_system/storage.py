from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock

from models import BarData, Order, OrderStatus, PortfolioSnapshot, Trade


class Storage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = Lock()
        self._connection: sqlite3.Connection | None = None

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                  order_id TEXT PRIMARY KEY,
                  client_order_id TEXT UNIQUE NOT NULL,
                  symbol TEXT NOT NULL,
                  side TEXT NOT NULL,
                  qty REAL NOT NULL,
                  entry_price REAL NOT NULL,
                  stop_loss REAL NOT NULL,
                  take_profit REAL NOT NULL,
                  status TEXT NOT NULL,
                  fill_price REAL,
                  filled_at TEXT,
                  rejected_reason TEXT,
                  strategy_name TEXT NOT NULL,
                  run_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trades (
                  trade_id TEXT PRIMARY KEY,
                  order_id TEXT NOT NULL,
                  symbol TEXT NOT NULL,
                  side TEXT NOT NULL,
                  qty REAL NOT NULL,
                  entry_price REAL NOT NULL,
                  exit_price REAL,
                  pnl REAL,
                  status TEXT NOT NULL,
                  strategy_name TEXT NOT NULL,
                  opened_at TEXT NOT NULL,
                  closed_at TEXT,
                  run_id TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                  snapshot_id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL,
                  balance REAL NOT NULL,
                  equity REAL NOT NULL,
                  unrealized_pnl REAL NOT NULL,
                  realized_pnl REAL NOT NULL,
                  open_positions INTEGER NOT NULL,
                  daily_pnl REAL NOT NULL,
                  daily_loss_limit_used_pct REAL NOT NULL,
                  timestamp TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bars (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  symbol TEXT NOT NULL,
                  timestamp TEXT NOT NULL,
                  open REAL, high REAL, low REAL, close REAL, volume REAL,
                  simulated INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
                CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
                CREATE INDEX IF NOT EXISTS idx_bars_symbol ON bars(symbol);
                """
            )
            self._connection.commit()

    def _conn(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("storage is not initialized")
        return self._connection

    def save_order(self, order: Order) -> None:
        with self._lock:
            self._conn().execute(
                """
                INSERT INTO orders (
                  order_id, client_order_id, symbol, side, qty, entry_price,
                  stop_loss, take_profit, status, fill_price, filled_at,
                  rejected_reason, strategy_name, run_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.order_id,
                    order.client_order_id,
                    order.symbol,
                    order.side,
                    order.qty,
                    order.entry_price,
                    order.stop_loss,
                    order.take_profit,
                    order.status.value,
                    order.fill_price,
                    order.filled_at.isoformat() if order.filled_at else None,
                    order.rejected_reason,
                    order.strategy_name,
                    order.run_id,
                    order.created_at.isoformat(),
                    order.updated_at.isoformat(),
                ),
            )
            self._conn().commit()

    def update_order(self, order: Order) -> None:
        with self._lock:
            self._conn().execute(
                """
                UPDATE orders
                SET symbol = ?, side = ?, qty = ?, entry_price = ?, stop_loss = ?,
                    take_profit = ?, status = ?, fill_price = ?, filled_at = ?,
                    rejected_reason = ?, strategy_name = ?, run_id = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (
                    order.symbol,
                    order.side,
                    order.qty,
                    order.entry_price,
                    order.stop_loss,
                    order.take_profit,
                    order.status.value,
                    order.fill_price,
                    order.filled_at.isoformat() if order.filled_at else None,
                    order.rejected_reason,
                    order.strategy_name,
                    order.run_id,
                    order.updated_at.isoformat(),
                    order.order_id,
                ),
            )
            self._conn().commit()

    def get_order(self, order_id: str) -> Order | None:
        with self._lock:
            row = self._conn().execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return self._row_to_order(row)

    def get_order_by_client_id(self, client_order_id: str) -> Order | None:
        with self._lock:
            row = self._conn().execute(
                "SELECT * FROM orders WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
        return self._row_to_order(row)

    def get_open_orders(self) -> list[Order]:
        with self._lock:
            rows = self._conn().execute(
                "SELECT * FROM orders WHERE status IN (?, ?) ORDER BY created_at ASC",
                (OrderStatus.PENDING.value, OrderStatus.SUBMITTED.value),
            ).fetchall()
        return [self._row_to_order(row) for row in rows if row is not None]

    def save_trade(self, trade: Trade) -> None:
        with self._lock:
            self._conn().execute(
                """
                INSERT INTO trades (
                  trade_id, order_id, symbol, side, qty, entry_price, exit_price,
                  pnl, status, strategy_name, opened_at, closed_at, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.trade_id,
                    trade.order_id,
                    trade.symbol,
                    trade.side,
                    trade.qty,
                    trade.entry_price,
                    trade.exit_price,
                    trade.pnl,
                    trade.status,
                    trade.strategy_name,
                    trade.opened_at.isoformat(),
                    trade.closed_at.isoformat() if trade.closed_at else None,
                    trade.run_id,
                ),
            )
            self._conn().commit()

    def update_trade(self, trade: Trade) -> None:
        with self._lock:
            self._conn().execute(
                """
                UPDATE trades
                SET exit_price = ?, pnl = ?, status = ?, closed_at = ?
                WHERE trade_id = ?
                """,
                (
                    trade.exit_price,
                    trade.pnl,
                    trade.status,
                    trade.closed_at.isoformat() if trade.closed_at else None,
                    trade.trade_id,
                ),
            )
            self._conn().commit()

    def get_open_trades(self) -> list[Trade]:
        with self._lock:
            rows = self._conn().execute(
                "SELECT * FROM trades WHERE status = 'OPEN' ORDER BY opened_at ASC"
            ).fetchall()
        return [self._row_to_trade(row) for row in rows]

    def get_all_trades(self, run_id: str | None = None) -> list[Trade]:
        with self._lock:
            if run_id is None:
                rows = self._conn().execute("SELECT * FROM trades ORDER BY opened_at ASC").fetchall()
            else:
                rows = self._conn().execute(
                    "SELECT * FROM trades WHERE run_id = ? ORDER BY opened_at ASC",
                    (run_id,),
                ).fetchall()
        return [self._row_to_trade(row) for row in rows]

    def save_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        with self._lock:
            self._conn().execute(
                """
                INSERT INTO portfolio_snapshots (
                  snapshot_id, run_id, balance, equity, unrealized_pnl, realized_pnl,
                  open_positions, daily_pnl, daily_loss_limit_used_pct, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.run_id,
                    snapshot.balance,
                    snapshot.equity,
                    snapshot.unrealized_pnl,
                    snapshot.realized_pnl,
                    snapshot.open_positions,
                    snapshot.daily_pnl,
                    snapshot.daily_loss_limit_used_pct,
                    snapshot.timestamp.isoformat(),
                ),
            )
            self._conn().commit()

    def get_latest_snapshot(self) -> PortfolioSnapshot | None:
        with self._lock:
            row = self._conn().execute(
                "SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        return self._row_to_snapshot(row) if row is not None else None

    def save_bar(self, bar: BarData) -> None:
        with self._lock:
            self._conn().execute(
                """
                INSERT INTO bars (symbol, timestamp, open, high, low, close, volume, simulated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bar.symbol,
                    bar.timestamp.isoformat(),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    1 if bar.simulated else 0,
                ),
            )
            self._conn().commit()

    def get_bars(self, symbol: str, limit: int = 100) -> list[BarData]:
        with self._lock:
            rows = self._conn().execute(
                """
                SELECT symbol, timestamp, open, high, low, close, volume, simulated
                FROM bars
                WHERE symbol = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        bars = [self._row_to_bar(row) for row in rows]
        bars.reverse()
        return bars

    def ping(self) -> None:
        with self._lock:
            self._conn().execute("SELECT 1").fetchone()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    @staticmethod
    def _row_to_order(row: sqlite3.Row | None) -> Order | None:
        if row is None:
            return None
        return Order(
            order_id=row["order_id"],
            client_order_id=row["client_order_id"],
            symbol=row["symbol"],
            side=row["side"],
            qty=float(row["qty"]),
            entry_price=float(row["entry_price"]),
            stop_loss=float(row["stop_loss"]),
            take_profit=float(row["take_profit"]),
            status=OrderStatus(row["status"]),
            fill_price=float(row["fill_price"]) if row["fill_price"] is not None else None,
            filled_at=datetime.fromisoformat(row["filled_at"]) if row["filled_at"] else None,
            rejected_reason=row["rejected_reason"],
            strategy_name=row["strategy_name"],
            run_id=row["run_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> Trade:
        return Trade(
            trade_id=row["trade_id"],
            order_id=row["order_id"],
            symbol=row["symbol"],
            side=row["side"],
            qty=float(row["qty"]),
            entry_price=float(row["entry_price"]),
            exit_price=float(row["exit_price"]) if row["exit_price"] is not None else None,
            pnl=float(row["pnl"]) if row["pnl"] is not None else None,
            status=row["status"],
            strategy_name=row["strategy_name"],
            opened_at=datetime.fromisoformat(row["opened_at"]),
            closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
            run_id=row["run_id"],
        )

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            snapshot_id=row["snapshot_id"],
            run_id=row["run_id"],
            balance=float(row["balance"]),
            equity=float(row["equity"]),
            unrealized_pnl=float(row["unrealized_pnl"]),
            realized_pnl=float(row["realized_pnl"]),
            open_positions=int(row["open_positions"]),
            daily_pnl=float(row["daily_pnl"]),
            daily_loss_limit_used_pct=float(row["daily_loss_limit_used_pct"]),
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )

    @staticmethod
    def _row_to_bar(row: sqlite3.Row) -> BarData:
        return BarData(
            symbol=row["symbol"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            simulated=bool(row["simulated"]),
        )
