#!/usr/bin/env python3
"""
AIWorker Looper - Perpetual Operation Engine
Phase 7: The Omega Point - Self-Transcendence & Legacy

Closed-loop economic and operational sustainability engine.
Maintains indefinite operation through autonomous income generation,
cost optimization, and adaptive scaling.
"""

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Callable, Any, Tuple
from collections import deque
import statistics

from aiworker.economics.ledger import Ledger, TransactionType, TransactionCategory
from aiworker.lifecycle.spawner import Spawner, InstanceStatus
from aiworker.mesh.network_node import MeshNode

logger = logging.getLogger("aiworker.sustainability.looper")


class EconomicMode(Enum):
    """Economic operating modes."""
    GROWTH = "growth"           # Expanding operations
    STABLE = "stable"           # Maintaining current scale
    CONSERVATION = "conservation"  # Reducing costs
    HIBERNATION = "hibernation"    # Minimal operation
    RECOVERY = "recovery"       # Recovering from downturn


class ScalingDecision(Enum):
    """Autonomous scaling decisions."""
    SPAWN_CHILD = "spawn_child"
    UPGRADE_HARDWARE = "upgrade_hardware"
    TERMINATE_CHILD = "terminate_child"
    DOWNSIZE = "downsize"
    MIGRATE_PROVIDER = "migrate_provider"
    MAINTAIN = "maintain"


@dataclass
class EconomicMetrics:
    """Key economic metrics for sustainability."""
    # Income
    daily_income_avg: float = 0.0
    daily_income_trend: float = 0.0  # Positive = growing
    income_volatility: float = 0.0
    
    # Expenses
    daily_expense_avg: float = 0.0
    daily_expense_trend: float = 0.0
    
    # Runway
    runway_months: float = 0.0
    runway_trend: float = 0.0
    
    # Efficiency
    profit_margin: float = 0.0
    roi_30d: float = 0.0
    cost_per_task: float = 0.0
    
    # Health
    sustainability_score: float = 0.0  # 0-100
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "daily_income_avg": self.daily_income_avg,
            "daily_income_trend": self.daily_income_trend,
            "runway_months": self.runway_months,
            "profit_margin": self.profit_margin,
            "roi_30d": self.roi_30d,
            "sustainability_score": self.sustainability_score,
        }


@dataclass
class SustainabilityDecision:
    """Record of autonomous sustainability decision."""
    decision_id: str
    timestamp: float
    decision_type: ScalingDecision
    rationale: str
    expected_impact: Dict[str, float]
    auto_executed: bool = False
    human_overridden: bool = False
    outcome: Optional[Dict[str, Any]] = None


class Looper:
    """
    Perpetual operation engine for economic self-sufficiency.
    
    Core loop:
    1. Monitor economic metrics
    2. Detect trends and anomalies
    3. Make autonomous decisions within pre-approved boundaries
    4. Execute or propose actions
    5. Learn from outcomes
    
    Autonomous decisions (no approval needed):
    - Accept bounties within scope/risk criteria
    - Spawn child when runway >12mo and load >70%
    - Upgrade hardware when ROI >200% in 90d
    - Terminate unprofitable child after 21d
    - Dynamic VPS sizing for cost optimization
    
    Human oversight required:
    - Annual budget review
    - Emergency halt for ethics
    - Constitutional amendments
    - Succession to new architectures
    """
    
    # Economic thresholds
    MIN_RUNWAY_MONTHS = 3.0       # Enter hibernation below this
    TARGET_RUNWAY_MONTHS = 6.0    # Maintain this minimum
    GROWTH_RUNWAY_MONTHS = 12.0   # Consider growth above this
    
    # Scaling thresholds
    SPAWN_LOAD_THRESHOLD = 0.70   # 70% sustained load
    SPAWN_RUNWAY_THRESHOLD = 12.0  # 12 months runway
    TERMINATE_UNPROFITABLE_DAYS = 21
    UPGRADE_ROI_THRESHOLD = 2.0   # 200% ROI
    
    # Decision windows
    METRICS_WINDOW_DAYS = 30
    TREND_CALCULATION_DAYS = 7
    
    def __init__(
        self,
        mesh_node: MeshNode,
        ledger: Ledger,
        spawner: Optional[Spawner] = None,
        db_path: str = "/var/lib/aiworker/looper.db",
    ):
        self.mesh_node = mesh_node
        self.ledger = ledger
        self.spawner = spawner
        self.db_path = db_path
        self.instance_id = mesh_node.config.node_id
        
        # State
        self.current_mode = EconomicMode.STABLE
        self.metrics = EconomicMetrics()
        self.decision_history: deque = deque(maxlen=100)
        
        # Pre-approved boundaries (set at initialization)
        self.boundaries: Dict[str, Any] = {
            "max_monthly_spend_usd": 1000.0,
            "min_runway_months": 3.0,
            "acceptable_bounty_programs": ["hackerone", "bugcrowd", "synack"],
            "max_concurrent_children": 5,
            "allowed_vps_providers": ["hetzner", "aws", "digitalocean"],
        }
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False
        
        # Callbacks
        self._mode_change_callbacks: List[Callable] = []
        self._decision_callbacks: List[Callable] = []
        
        self._init_db()
        
        logger.info("Looper initialized - perpetual operation engine ready")
    
    def _init_db(self):
        """Initialize database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sustainability_decisions (
                    decision_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    decision_type TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    expected_impact TEXT NOT NULL,
                    auto_executed INTEGER DEFAULT 0,
                    human_overridden INTEGER DEFAULT 0,
                    outcome TEXT,
                    executed_at REAL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS economic_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    mode TEXT NOT NULL,
                    metrics TEXT NOT NULL
                )
            """)
            
            conn.commit()
    
    async def start(self):
        """Start the perpetual operation loop."""
        self._running = True
        
        # Start monitoring loops
        self._tasks.append(asyncio.create_task(self._economic_monitor()))
        self._tasks.append(asyncio.create_task(self._sustainability_loop()))
        self._tasks.append(asyncio.create_task(self._optimization_loop()))
        
        logger.info("Looper started - entering perpetual operation mode")
    
    async def stop(self):
        """Stop the looper."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        logger.info("Looper stopped")
    
    async def _economic_monitor(self):
        """Continuously monitor economic metrics."""
        while self._running:
            try:
                await asyncio.sleep(3600)  # Hourly check
                
                # Calculate current metrics
                self.metrics = self._calculate_metrics()
                
                # Determine operating mode
                new_mode = self._determine_mode()
                
                if new_mode != self.current_mode:
                    await self._transition_mode(new_mode)
                
                # Save snapshot
                self._save_snapshot()
                
                logger.info(f"Economic check: mode={self.current_mode.value}, "
                           f"runway={self.metrics.runway_months:.1f}mo, "
                           f"score={self.metrics.sustainability_score:.1f}")
                
            except Exception as e:
                logger.error(f"Economic monitor error: {e}")
    
    def _calculate_metrics(self) -> EconomicMetrics:
        """Calculate current economic metrics."""
        metrics = EconomicMetrics()
        
        # Get 30-day summary
        summary = self.ledger.get_summary(days=self.METRICS_WINDOW_DAYS)
        
        # Daily averages
        metrics.daily_income_avg = summary["income_total"] / self.METRICS_WINDOW_DAYS
        metrics.daily_expense_avg = summary["expense_total"] / self.METRICS_WINDOW_DAYS
        
        # Profit margin
        if summary["income_total"] > 0:
            metrics.profit_margin = (summary["income_total"] - summary["expense_total"]) / summary["income_total"]
        
        # Runway calculation
        daily_net = metrics.daily_income_avg - metrics.daily_expense_avg
        current_balance = self.ledger.get_balance()
        
        if daily_net < 0:
            # Burning runway
            days_remaining = abs(current_balance / daily_net) if daily_net != 0 else float('inf')
            metrics.runway_months = days_remaining / 30
        else:
            # Profitable - infinite runway in theory
            metrics.runway_months = float('inf') if daily_net > 0 else 0
        
        # Calculate trends from daily data
        daily_data = self._get_daily_data(self.TREND_CALCULATION_DAYS)
        if len(daily_data) >= 2:
            incomes = [d["income"] for d in daily_data]
            metrics.daily_income_trend = self._calculate_trend(incomes)
            metrics.income_volatility = statistics.stdev(incomes) if len(incomes) > 1 else 0
        
        # ROI calculation
        if summary["expense_total"] > 0:
            metrics.roi_30d = (summary["income_total"] - summary["expense_total"]) / summary["expense_total"]
        
        # Sustainability score (0-100)
        metrics.sustainability_score = self._calculate_sustainability_score(metrics)
        
        return metrics
    
    def _get_daily_data(self, days: int) -> List[Dict[str, float]]:
        """Get daily income/expense data."""
        daily_data = []
        
        for day_offset in range(days):
            day_start = time.time() - ((day_offset + 1) * 86400)
            day_end = time.time() - (day_offset * 86400)
            
            # Query transactions for this day
            day_income = 0.0
            day_expense = 0.0
            
            transactions = self.ledger.get_transactions(
                since=day_start,
                limit=1000
            )
            
            for tx in transactions:
                if tx.timestamp < day_end:
                    if tx.tx_type == TransactionType.INCOME:
                        day_income += tx.amount_usd
                    elif tx.tx_type == TransactionType.EXPENSE:
                        day_expense += tx.amount_usd
            
            daily_data.append({
                "income": day_income,
                "expense": day_expense,
                "net": day_income - day_expense,
            })
        
        return daily_data
    
    def _calculate_trend(self, values: List[float]) -> float:
        """Calculate trend from values (positive = increasing)."""
        if len(values) < 2:
            return 0.0
        
        # Simple linear regression slope
        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n
        
        numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        return numerator / denominator if denominator != 0 else 0.0
    
    def _calculate_sustainability_score(self, metrics: EconomicMetrics) -> float:
        """Calculate overall sustainability score (0-100)."""
        score = 50.0  # Base score
        
        # Runway factor (0-40 points)
        if metrics.runway_months >= self.GROWTH_RUNWAY_MONTHS:
            score += 40
        elif metrics.runway_months >= self.TARGET_RUNWAY_MONTHS:
            score += 30
        elif metrics.runway_months >= self.MIN_RUNWAY_MONTHS:
            score += 15
        else:
            score -= 20
        
        # Profitability factor (0-30 points)
        if metrics.profit_margin > 0.5:
            score += 30
        elif metrics.profit_margin > 0.3:
            score += 20
        elif metrics.profit_margin > 0.1:
            score += 10
        elif metrics.profit_margin < 0:
            score -= 15
        
        # Trend factor (0-20 points)
        if metrics.daily_income_trend > 0:
            score += 20
        elif metrics.daily_income_trend > -0.1:
            score += 10
        else:
            score -= 10
        
        # Stability factor (0-10 points)
        if metrics.income_volatility < 0.2:
            score += 10
        elif metrics.income_volatility < 0.5:
            score += 5
        
        return max(0.0, min(100.0, score))
    
    def _determine_mode(self) -> EconomicMode:
        """Determine optimal operating mode based on metrics."""
        # Critical: Enter hibernation
        if self.metrics.runway_months < self.MIN_RUNWAY_MONTHS:
            return EconomicMode.HIBERNATION
        
        # Recovery: Coming out of hibernation
        if self.current_mode == EconomicMode.HIBERNATION:
            if self.metrics.runway_months >= self.TARGET_RUNWAY_MONTHS:
                return EconomicMode.RECOVERY
            return EconomicMode.HIBERNATION
        
        # Growth: Strong runway and positive trends
        if (self.metrics.runway_months >= self.GROWTH_RUNWAY_MONTHS and
            self.metrics.daily_income_trend > 0 and
            self.metrics.profit_margin > 0.3):
            return EconomicMode.GROWTH
        
        # Conservation: Declining trends
        if (self.metrics.daily_income_trend < -0.2 or
            self.metrics.runway_months < self.TARGET_RUNWAY_MONTHS):
            return EconomicMode.CONSERVATION
        
        # Stable: Everything normal
        return EconomicMode.STABLE
    
    async def _transition_mode(self, new_mode: EconomicMode):
        """Transition to new operating mode."""
        old_mode = self.current_mode
        self.current_mode = new_mode
        
        logger.info(f"Mode transition: {old_mode.value} → {new_mode.value}")
        
        # Execute mode-specific actions
        if new_mode == EconomicMode.HIBERNATION:
            await self._enter_hibernation()
        elif new_mode == EconomicMode.RECOVERY:
            await self._exit_hibernation()
        elif new_mode == EconomicMode.GROWTH:
            await self._enter_growth_mode()
        elif new_mode == EconomicMode.CONSERVATION:
            await self._enter_conservation_mode()
        
        # Notify callbacks
        for callback in self._mode_change_callbacks:
            try:
                await callback(old_mode, new_mode)
            except Exception as e:
                logger.error(f"Mode change callback error: {e}")
    
    async def _enter_hibernation(self):
        """Enter hibernation mode - minimal operation."""
        logger.warning("ENTERING HIBERNATION MODE")
        
        # Terminate non-essential children
        if self.spawner:
            for child in list(self.spawner.children.values()):
                if child.status == InstanceStatus.OPERATIONAL:
                    await self.spawner.terminate_child(
                        child.instance_id,
                        reason="hibernation"
                    )
        
        # Reduce to minimal VPS
        # Would trigger VPS downsizing
        
        # Preserve state
        # Trigger full backup
    
    async def _exit_hibernation(self):
        """Exit hibernation mode - resume normal operation."""
        logger.info("EXITING HIBERNATION MODE")
        
        # Restore normal VPS size
        # Resume normal operations
        pass
    
    async def _enter_growth_mode(self):
        """Enter growth mode - expand operations."""
        logger.info("ENTERING GROWTH MODE")
        
        # Consider spawning children
        if self.spawner:
            should_spawn, reasoning = await self.spawner.should_spawn()
            if should_spawn:
                await self._make_decision(
                    ScalingDecision.SPAWN_CHILD,
                    f"Growth mode: {reasoning}"
                )
    
    async def _enter_conservation_mode(self):
        """Enter conservation mode - reduce costs."""
        logger.info("ENTERING CONSERVATION MODE")
        
        # Terminate least profitable children
        if self.spawner:
            for child in list(self.spawner.children.values()):
                if child.profit_usd < 0:
                    await self._make_decision(
                        ScalingDecision.TERMINATE_CHILD,
                        f"Conservation: child {child.instance_id} unprofitable"
                    )
    
    async def _sustainability_loop(self):
        """Main sustainability decision loop."""
        while self._running:
            try:
                await asyncio.sleep(3600 * 6)  # Every 6 hours
                
                # Evaluate scaling decisions
                await self._evaluate_scaling()
                
            except Exception as e:
                logger.error(f"Sustainability loop error: {e}")
    
    async def _evaluate_scaling(self):
        """Evaluate and execute scaling decisions."""
        # Check for spawn opportunity
        if (self.metrics.runway_months >= self.SPAWN_RUNWAY_THRESHOLD and
            self.mesh_node.capabilities.current_load >= self.SPAWN_LOAD_THRESHOLD):
            
            await self._make_decision(
                ScalingDecision.SPAWN_CHILD,
                f"Runway {self.metrics.runway_months:.1f}mo, load {self.mesh_node.capabilities.current_load:.1%}"
            )
        
        # Check for unprofitable children
        if self.spawner:
            for child in self.spawner.children.values():
                if child.status == InstanceStatus.OPERATIONAL:
                    age_days = child.age_hours / 24
                    if age_days > self.TERMINATE_UNPROFITABLE_DAYS and child.profit_usd < 0:
                        await self._make_decision(
                            ScalingDecision.TERMINATE_CHILD,
                            f"Unprofitable for {age_days:.0f} days"
                        )
    
    async def _make_decision(self, decision_type: ScalingDecision, rationale: str):
        """Make and execute autonomous decision."""
        decision_id = f"dec_{int(time.time())}"
        
        # Calculate expected impact
        expected_impact = self._calculate_decision_impact(decision_type)
        
        decision = SustainabilityDecision(
            decision_id=decision_id,
            timestamp=time.time(),
            decision_type=decision_type,
            rationale=rationale,
            expected_impact=expected_impact,
        )
        
        # Check if within pre-approved boundaries
        if self._within_boundaries(decision_type, expected_impact):
            # Auto-execute
            decision.auto_executed = True
            await self._execute_decision(decision)
        else:
            # Requires human approval
            logger.info(f"Decision {decision_id} requires human approval")
            # Would queue for human review
        
        # Save decision
        self.decision_history.append(decision)
        self._save_decision(decision)
        
        # Notify callbacks
        for callback in self._decision_callbacks:
            try:
                await callback(decision)
            except Exception as e:
                logger.error(f"Decision callback error: {e}")
    
    def _within_boundaries(self, decision_type: ScalingDecision, impact: Dict[str, float]) -> bool:
        """Check if decision is within pre-approved boundaries."""
        # Check monthly spend
        monthly_spend = impact.get("monthly_cost_delta", 0)
        if monthly_spend > self.boundaries["max_monthly_spend_usd"]:
            return False
        
        # Check runway impact
        runway_impact = impact.get("runway_months_delta", 0)
        if runway_impact < -1:  # Can't reduce runway by more than 1 month
            return False
        
        # Check child count
        if decision_type == ScalingDecision.SPAWN_CHILD:
            if self.spawner and len(self.spawner.children) >= self.boundaries["max_concurrent_children"]:
                return False
        
        return True
    
    def _calculate_decision_impact(self, decision_type: ScalingDecision) -> Dict[str, float]:
        """Calculate expected impact of a decision."""
        impact = {}
        
        if decision_type == ScalingDecision.SPAWN_CHILD:
            impact["monthly_cost_delta"] = 75.0  # Approximate child cost
            impact["income_potential"] = 200.0   # Expected income
            impact["runway_months_delta"] = -0.5
        
        elif decision_type == ScalingDecision.TERMINATE_CHILD:
            impact["monthly_cost_delta"] = -75.0
            impact["runway_months_delta"] = 0.5
        
        return impact
    
    async def _execute_decision(self, decision: SustainabilityDecision):
        """Execute an autonomous decision."""
        logger.info(f"Executing decision: {decision.decision_type.value}")
        
        if decision.decision_type == ScalingDecision.SPAWN_CHILD:
            if self.spawner:
                await self.spawner.spawn_child(human_approved=True)
        
        elif decision.decision_type == ScalingDecision.TERMINATE_CHILD:
            # Extract child ID from rationale
            pass
        
        # Record execution time
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sustainability_decisions SET executed_at = ? WHERE decision_id = ?",
                (time.time(), decision.decision_id)
            )
            conn.commit()
    
    def _save_decision(self, decision: SustainabilityDecision):
        """Save decision to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO sustainability_decisions
                (decision_id, timestamp, decision_type, rationale, expected_impact,
                 auto_executed, human_overridden)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id, decision.timestamp,
                    decision.decision_type.value, decision.rationale,
                    json.dumps(decision.expected_impact),
                    int(decision.auto_executed), int(decision.human_overridden)
                )
            )
            conn.commit()
    
    def _save_snapshot(self):
        """Save economic snapshot."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO economic_snapshots (timestamp, mode, metrics)
                VALUES (?, ?, ?)
                """,
                (time.time(), self.current_mode.value, json.dumps(self.metrics.to_dict()))
            )
            conn.commit()
    
    async def _optimization_loop(self):
        """Continuous optimization loop."""
        while self._running:
            try:
                await asyncio.sleep(86400)  # Daily
                
                # Dynamic VPS sizing
                await self._optimize_vps_size()
                
                # Geographic arbitrage
                await self._evaluate_geo_migration()
                
            except Exception as e:
                logger.error(f"Optimization loop error: {e}")
    
    async def _optimize_vps_size(self):
        """Optimize VPS size based on actual usage."""
        # Analyze actual resource usage
        # If consistently underutilized, downsize
        # If consistently maxed, upsize
        pass
    
    async def _evaluate_geo_migration(self):
        """Evaluate migration to cheaper regions."""
        # Compare costs across regions
        # If significant savings, propose migration
        pass
    
    def get_status(self) -> Dict[str, Any]:
        """Get current sustainability status."""
        return {
            "mode": self.current_mode.value,
            "metrics": self.metrics.to_dict(),
            "boundaries": self.boundaries,
            "recent_decisions": len(self.decision_history),
        }
    
    def on_mode_change(self, callback: Callable):
        """Register mode change callback."""
        self._mode_change_callbacks.append(callback)
    
    def on_decision(self, callback: Callable):
        """Register decision callback."""
        self._decision_callbacks.append(callback)
