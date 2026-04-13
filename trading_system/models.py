from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class BarData(BaseModel):
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    simulated: bool = True


class Signal(BaseModel):
    signal_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    strategy_name: str
    reason: str
    entry_price: float
    stop_loss: float
    take_profit: float
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Order(BaseModel):
    order_id: str
    client_order_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: float
    entry_price: float
    stop_loss: float
    take_profit: float
    status: OrderStatus = OrderStatus.PENDING
    fill_price: float | None = None
    filled_at: datetime | None = None
    rejected_reason: str | None = None
    strategy_name: str
    run_id: str
    created_at: datetime
    updated_at: datetime


class Position(BaseModel):
    position_id: str
    symbol: str
    side: Literal["LONG", "SHORT"]
    qty: float
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    unrealized_pnl: float
    opened_at: datetime
    order_id: str


class Trade(BaseModel):
    trade_id: str
    order_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: float
    entry_price: float
    exit_price: float | None = None
    pnl: float | None = None
    status: Literal["OPEN", "CLOSED"]
    strategy_name: str
    opened_at: datetime
    closed_at: datetime | None = None
    run_id: str


class RiskDecision(BaseModel):
    approved: bool
    reason: str
    adjusted_qty: float | None = None
    signal: Signal


class PortfolioSnapshot(BaseModel):
    snapshot_id: str
    run_id: str
    balance: float
    equity: float
    unrealized_pnl: float
    realized_pnl: float
    open_positions: int
    daily_pnl: float
    daily_loss_limit_used_pct: float
    timestamp: datetime


class HealthStatus(BaseModel):
    status: Literal["HEALTHY", "DEGRADED", "CRITICAL"]
    data_feed_ok: bool
    storage_ok: bool
    kill_switch_active: bool
    last_bar_age_seconds: float
    open_positions: int
    daily_pnl: float
    alerts: list[str]
    checked_at: datetime
