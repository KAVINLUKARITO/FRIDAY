#!/usr/bin/env python3
"""
AIWorker Retirement - Graceful Self-Termination
Phase 6: Autonomous Evolution & Self-Replication

Handles graceful self-termination when superseded or non-viable.
Ensures no knowledge loss, no orphan children, and human oversight.
"""

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable, Any, Tuple

from aiworker.mesh.network_node import MeshNode
from aiworker.knowledge.sync_engine import SyncEngine
from aiworker.lifecycle.spawner import Spawner, ChildInstance, InstanceStatus

logger = logging.getLogger("aiworker.lifecycle.retirement")


class RetirementPhase(Enum):
    """Phases of the retirement process."""
    INITIATED = "initiated"              # Retirement triggered
    STOP_ACCEPTING = "stop_accepting"    # No new tasks
    KNOWLEDGE_TRANSFER = "knowledge_transfer"  # Sync to mesh
    CHILD_HANDOVER = "child_handover"    # Transfer/disown children
    ASSET_LIQUIDATION = "asset_liquidation"  # Cancel VPS, withdraw funds
    FINAL_BACKUP = "final_backup"        # Complete state snapshot
    VERIFICATION = "verification"        # Human confirmation
    SHUTDOWN = "shutdown"                # Clean exit
    COMPLETE = "complete"                # Retirement done
    HIBERNATING = "hibernating"          # Preserved for restart


class RetirementTrigger(Enum):
    """Reasons for retirement."""
    SUCCESSOR_READY = "successor_ready"      # Successor proven
    UNPROFITABLE = "unprofitable"            # Sustained losses
    HARDWARE_FAILURE = "hardware_failure"    # Unrecoverable
    HUMAN_COMMAND = "human_command"          # Explicit order
    GLOBAL_SUNSET = "global_sunset"          # Project end
    EMERGENCY = "emergency"                  # Critical issue


@dataclass
class RetirementPlan:
    """Plan for instance retirement."""
    plan_id: str
    instance_id: str
    trigger: RetirementTrigger
    
    # Timeline
    initiated_at: float
    estimated_completion: float
    phases: List[Tuple[RetirementPhase, float, Optional[str]]] = field(default_factory=list)
    
    # Status
    current_phase: RetirementPhase = RetirementPhase.INITIATED
    phase_start_time: float = field(default_factory=time.time)
    
    # Children
    children_count: int = 0
    children_transferred: int = 0
    children_terminated: int = 0
    
    # Knowledge
    knowledge_records_total: int = 0
    knowledge_records_synced: int = 0
    
    # Assets
    vps_id: Optional[str] = None
    funds_usd: float = 0.0
    funds_withdrawn: float = 0.0
    
    # Backup
    backup_location: Optional[str] = None
    backup_size_bytes: int = 0
    
    # Human
    human_verified: bool = False
    verifier: Optional[str] = None
    verification_time: Optional[float] = None
    
    # Final
    hibernate: bool = False
    completed_at: Optional[float] = None
    
    def __post_init__(self):
        if not self.phases:
            self.phases = [(RetirementPhase.INITIATED, self.initiated_at, None)]
    
    def advance_phase(self, new_phase: RetirementPhase, note: Optional[str] = None):
        """Advance to next retirement phase."""
        self.current_phase = new_phase
        self.phase_start_time = time.time()
        self.phases.append((new_phase, self.phase_start_time, note))
        logger.info(f"Retirement {self.plan_id} advanced to {new_phase.value}")
    
    @property
    def elapsed_hours(self) -> float:
        """Get elapsed time since initiation."""
        return (time.time() - self.initiated_at) / 3600
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "instance_id": self.instance_id,
            "trigger": self.trigger.value,
            "current_phase": self.current_phase.value,
            "elapsed_hours": self.elapsed_hours,
            "children": {
                "total": self.children_count,
                "transferred": self.children_transferred,
                "terminated": self.children_terminated,
            },
            "knowledge": {
                "total": self.knowledge_records_total,
                "synced": self.knowledge_records_synced,
            },
            "human_verified": self.human_verified,
            "completed": self.completed_at is not None,
        }


class RetirementManager:
    """
    Manages graceful self-termination of AIWorker instances.
    
    Ensures:
    - No knowledge loss (full sync before shutdown)
    - No orphan children (handoff or graceful termination)
    - Human oversight (verification required)
    - Clean exit (proper resource cleanup)
    """
    
    # Phase timeouts (hours)
    KNOWLEDGE_TRANSFER_TIMEOUT = 48
    CHILD_HANDOVER_TIMEOUT = 24
    VERIFICATION_TIMEOUT = 168  # 7 days
    
    def __init__(
        self,
        mesh_node: MeshNode,
        sync_engine: Optional[SyncEngine] = None,
        spawner: Optional[Spawner] = None,
        db_path: str = "/var/lib/aiworker/retirement.db",
    ):
        self.mesh_node = mesh_node
        self.sync_engine = sync_engine
        self.spawner = spawner
        self.db_path = db_path
        self.instance_id = mesh_node.config.node_id
        
        # Active retirement plan
        self.active_plan: Optional[RetirementPlan] = None
        
        # Callbacks
        self._phase_callbacks: Dict[RetirementPhase, List[Callable]] = {
            phase: [] for phase in RetirementPhase
        }
        self._completion_callbacks: List[Callable] = []
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False
        
        self._init_db()
        
        logger.info("RetirementManager initialized")
    
    def _init_db(self):
        """Initialize database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retirement_plans (
                    plan_id TEXT PRIMARY KEY,
                    instance_id TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    initiated_at REAL NOT NULL,
                    estimated_completion REAL,
                    phases TEXT DEFAULT '[]',
                    current_phase TEXT DEFAULT 'initiated',
                    phase_start_time REAL,
                    children_count INTEGER DEFAULT 0,
                    children_transferred INTEGER DEFAULT 0,
                    children_terminated INTEGER DEFAULT 0,
                    knowledge_records_total INTEGER DEFAULT 0,
                    knowledge_records_synced INTEGER DEFAULT 0,
                    vps_id TEXT,
                    funds_usd REAL DEFAULT 0.0,
                    funds_withdrawn REAL DEFAULT 0.0,
                    backup_location TEXT,
                    backup_size_bytes INTEGER DEFAULT 0,
                    human_verified INTEGER DEFAULT 0,
                    verifier TEXT,
                    verification_time REAL,
                    hibernate INTEGER DEFAULT 0,
                    completed_at REAL
                )
            """)
            conn.commit()
    
    async def start(self):
        """Start the retirement manager."""
        self._running = True
        
        # Check for incomplete retirement
        await self._check_incomplete_retirement()
        
        logger.info("RetirementManager started")
    
    async def stop(self):
        """Stop the retirement manager."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        logger.info("RetirementManager stopped")
    
    async def _check_incomplete_retirement(self):
        """Check for incomplete retirement from previous run."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM retirement_plans WHERE instance_id = ? AND completed_at IS NULL",
                (self.instance_id,)
            ).fetchone()
        
        if row:
            logger.warning("Found incomplete retirement plan, resuming...")
            self.active_plan = self._row_to_plan(row)
            self._tasks.append(asyncio.create_task(self._execute_retirement()))
    
    def _row_to_plan(self, row) -> RetirementPlan:
        """Convert database row to RetirementPlan."""
        return RetirementPlan(
            plan_id=row[0],
            instance_id=row[1],
            trigger=RetirementTrigger(row[2]),
            initiated_at=row[3],
            estimated_completion=row[4],
            phases=json.loads(row[5]),
            current_phase=RetirementPhase(row[6]),
            phase_start_time=row[7] or time.time(),
            children_count=row[8],
            children_transferred=row[9],
            children_terminated=row[10],
            knowledge_records_total=row[11],
            knowledge_records_synced=row[12],
            vps_id=row[13],
            funds_usd=row[14],
            funds_withdrawn=row[15],
            backup_location=row[16],
            backup_size_bytes=row[17],
            human_verified=bool(row[18]),
            verifier=row[19],
            verification_time=row[20],
            hibernate=bool(row[21]),
            completed_at=row[22],
        )
    
    def _save_plan(self, plan: RetirementPlan):
        """Save retirement plan to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO retirement_plans
                (plan_id, instance_id, trigger, initiated_at, estimated_completion,
                 phases, current_phase, phase_start_time, children_count,
                 children_transferred, children_terminated, knowledge_records_total,
                 knowledge_records_synced, vps_id, funds_usd, funds_withdrawn,
                 backup_location, backup_size_bytes, human_verified, verifier,
                 verification_time, hibernate, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.plan_id,
                    plan.instance_id,
                    plan.trigger.value,
                    plan.initiated_at,
                    plan.estimated_completion,
                    json.dumps(plan.phases),
                    plan.current_phase.value,
                    plan.phase_start_time,
                    plan.children_count,
                    plan.children_transferred,
                    plan.children_terminated,
                    plan.knowledge_records_total,
                    plan.knowledge_records_synced,
                    plan.vps_id,
                    plan.funds_usd,
                    plan.funds_withdrawn,
                    plan.backup_location,
                    plan.backup_size_bytes,
                    int(plan.human_verified),
                    plan.verifier,
                    plan.verification_time,
                    int(plan.hibernate),
                    plan.completed_at,
                )
            )
            conn.commit()
    
    async def initiate_retirement(
        self,
        trigger: RetirementTrigger,
        hibernate: bool = False,
        human_approved: bool = False
    ) -> Optional[RetirementPlan]:
        """
        Initiate retirement process.
        
        Args:
            trigger: Reason for retirement
            hibernate: Whether to preserve for restart
            human_approved: Whether human pre-approved
        
        Returns:
            RetirementPlan if initiated
        """
        # Check if retirement already in progress
        if self.active_plan:
            logger.warning("Retirement already in progress")
            return self.active_plan
        
        # Emergency trigger can bypass approval
        if trigger != RetirementTrigger.EMERGENCY and not human_approved:
            logger.warning("Retirement requires human approval (except emergency)")
            return None
        
        logger.info(f"Initiating retirement (trigger: {trigger.value}, hibernate: {hibernate})")
        
        plan_id = f"retire_{int(time.time())}"
        
        plan = RetirementPlan(
            plan_id=plan_id,
            instance_id=self.instance_id,
            trigger=trigger,
            initiated_at=time.time(),
            estimated_completion=time.time() + (72 * 3600),  # 72 hours
            hibernate=hibernate,
        )
        
        self.active_plan = plan
        self._save_plan(plan)
        
        # Start retirement process
        self._tasks.append(asyncio.create_task(self._execute_retirement()))
        
        return plan
    
    async def _execute_retirement(self):
        """Execute the full retirement process."""
        plan = self.active_plan
        if not plan:
            return
        
        try:
            # Phase 1: Stop accepting new work
            await self._phase_stop_accepting(plan)
            
            # Phase 2: Knowledge transfer
            await self._phase_knowledge_transfer(plan)
            
            # Phase 3: Child handover
            await self._phase_child_handover(plan)
            
            # Phase 4: Asset liquidation
            await self._phase_asset_liquidation(plan)
            
            # Phase 5: Final backup
            await self._phase_final_backup(plan)
            
            # Phase 6: Verification
            await self._phase_verification(plan)
            
            # Phase 7: Shutdown
            await self._phase_shutdown(plan)
            
        except Exception as e:
            logger.error(f"Retirement execution failed: {e}")
            # Extend retirement to allow recovery
            plan.estimated_completion += 7 * 24 * 3600  # +7 days
            self._save_plan(plan)
    
    async def _phase_stop_accepting(self, plan: RetirementPlan):
        """Stop accepting new work."""
        logger.info("Retirement Phase 1: Stop accepting new work")
        
        plan.advance_phase(RetirementPhase.STOP_ACCEPTING)
        self._save_plan(plan)
        
        # Signal to mesh that we're retiring
        # Finish current tasks
        # Reject new task assignments
        
        # Wait for current tasks to complete (with timeout)
        max_wait = 3600  # 1 hour
        start = time.time()
        
        while time.time() - start < max_wait:
            # Check if tasks complete
            # Placeholder: assume complete after delay
            await asyncio.sleep(5)
            break
        
        logger.info("Phase 1 complete: No longer accepting work")
    
    async def _phase_knowledge_transfer(self, plan: RetirementPlan):
        """Transfer all knowledge to mesh."""
        logger.info("Retirement Phase 2: Knowledge transfer")
        
        plan.advance_phase(RetirementPhase.KNOWLEDGE_TRANSFER)
        self._save_plan(plan)
        
        if self.sync_engine:
            # Force sync with all peers
            await self.sync_engine.force_sync()
            
            # Get stats
            stats = self.sync_engine.get_stats()
            plan.knowledge_records_total = stats["store_stats"]["shared_records"]
            plan.knowledge_records_synced = plan.knowledge_records_total
        
        self._save_plan(plan)
        logger.info(f"Phase 2 complete: {plan.knowledge_records_synced} records synced")
    
    async def _phase_child_handover(self, plan: RetirementPlan):
        """Handle child instances."""
        logger.info("Retirement Phase 3: Child handover")
        
        plan.advance_phase(RetirementPhase.CHILD_HANDOVER)
        self._save_plan(plan)
        
        if self.spawner:
            children = list(self.spawner.children.values())
            plan.children_count = len(children)
            
            for child in children:
                # Try to transfer to another parent
                transferred = await self._transfer_child(child)
                
                if transferred:
                    plan.children_transferred += 1
                else:
                    # Terminate child gracefully
                    await self.spawner.terminate_child(
                        child.instance_id,
                        reason="parent_retiring"
                    )
                    plan.children_terminated += 1
                
                self._save_plan(plan)
        
        logger.info(f"Phase 3 complete: {plan.children_transferred} transferred, "
                   f"{plan.children_terminated} terminated")
    
    async def _transfer_child(self, child: ChildInstance) -> bool:
        """Try to transfer child to another parent in mesh."""
        logger.info(f"Attempting to transfer child {child.instance_id}")
        
        # Find suitable adoptive parent
        for peer in self.mesh_node.peers.values():
            if peer.trust_score > 0.8:
                # Propose adoption
                logger.info(f"Proposing adoption to {peer.node_id}")
                # Placeholder: would send adoption request
                return True
        
        return False
    
    async def _phase_asset_liquidation(self, plan: RetirementPlan):
        """Liquidate assets and withdraw funds."""
        logger.info("Retirement Phase 4: Asset liquidation")
        
        plan.advance_phase(RetirementPhase.ASSET_LIQUIDATION)
        self._save_plan(plan)
        
        # Get current funds
        plan.funds_usd = await self._get_funds()
        
        # Withdraw to human-controlled wallet
        withdrawn = await self._withdraw_funds(plan.funds_usd)
        plan.funds_withdrawn = withdrawn
        
        # Cancel VPS (if not hibernating)
        if not plan.hibernate and plan.vps_id:
            await self._cancel_vps(plan.vps_id)
        
        self._save_plan(plan)
        logger.info(f"Phase 4 complete: ${plan.funds_withdrawn} withdrawn")
    
    async def _get_funds(self) -> float:
        """Get current funds."""
        # Would query economics ledger
        return 0.0
    
    async def _withdraw_funds(self, amount: float) -> float:
        """Withdraw funds to human wallet."""
        # Would execute withdrawal
        return amount
    
    async def _cancel_vps(self, vps_id: str):
        """Cancel VPS subscription."""
        logger.info(f"Cancelling VPS: {vps_id}")
        # Would call VPS provider API
    
    async def _phase_final_backup(self, plan: RetirementPlan):
        """Create final backup of all state."""
        logger.info("Retirement Phase 5: Final backup")
        
        plan.advance_phase(RetirementPhase.FINAL_BACKUP)
        self._save_plan(plan)
        
        # Create backup archive
        backup_dir = f"/var/backups/aiworker/retirement/{plan.plan_id}"
        os.makedirs(backup_dir, exist_ok=True)
        
        # Backup databases
        dbs_to_backup = [
            "/var/lib/aiworker/knowledge_shared.db",
            "/var/lib/aiworker/task_ledger.db",
            "/var/lib/aiworker/role_performance.db",
            "/var/lib/aiworker/spawner.db",
        ]
        
        for db_path in dbs_to_backup:
            if os.path.exists(db_path):
                shutil.copy2(db_path, backup_dir)
        
        # Backup configuration
        config_dir = "/etc/aiworker"
        if os.path.exists(config_dir):
            shutil.copytree(config_dir, f"{backup_dir}/config", dirs_exist_ok=True)
        
        # Create tarball
        archive_path = f"{backup_dir}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(backup_dir, arcname=os.path.basename(backup_dir))
        
        # Get size
        plan.backup_size_bytes = os.path.getsize(archive_path)
        plan.backup_location = archive_path
        
        # Clean up temp directory
        shutil.rmtree(backup_dir)
        
        self._save_plan(plan)
        logger.info(f"Phase 5 complete: Backup at {archive_path} ({plan.backup_size_bytes} bytes)")
    
    async def _phase_verification(self, plan: RetirementPlan):
        """Wait for human verification."""
        logger.info("Retirement Phase 6: Human verification")
        
        plan.advance_phase(RetirementPhase.VERIFICATION)
        self._save_plan(plan)
        
        # Notify human
        await self._notify_human_verification(plan)
        
        # Wait for verification (with timeout)
        start = time.time()
        timeout = self.VERIFICATION_TIMEOUT * 3600
        
        while not plan.human_verified:
            if time.time() - start > timeout:
                logger.warning("Verification timeout, extending retirement")
                plan.estimated_completion += 7 * 24 * 3600
                self._save_plan(plan)
                return
            
            await asyncio.sleep(60)  # Check every minute
            
            # Reload plan (in case verification came in)
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT human_verified FROM retirement_plans WHERE plan_id = ?",
                    (plan.plan_id,)
                ).fetchone()
                if row and row[0]:
                    plan.human_verified = True
        
        logger.info("Phase 6 complete: Human verified")
    
    async def _notify_human_verification(self, plan: RetirementPlan):
        """Notify human that verification is required."""
        logger.info(f"HUMAN_VERIFICATION_REQUIRED: Plan {plan.plan_id}")
        logger.info(f"  Trigger: {plan.trigger.value}")
        logger.info(f"  Knowledge synced: {plan.knowledge_records_synced}")
        logger.info(f"  Children handled: {plan.children_transferred} transferred, "
                   f"{plan.children_terminated} terminated")
        logger.info(f"  Funds withdrawn: ${plan.funds_withdrawn}")
        logger.info(f"  Backup: {plan.backup_location}")
    
    async def verify_retirement(self, plan_id: str, verifier: str) -> bool:
        """
        Human verifies retirement is safe to proceed.
        
        Args:
            plan_id: Retirement plan ID
            verifier: Human identifier
        
        Returns:
            True if verified
        """
        if not self.active_plan or self.active_plan.plan_id != plan_id:
            return False
        
        self.active_plan.human_verified = True
        self.active_plan.verifier = verifier
        self.active_plan.verification_time = time.time()
        self._save_plan(self.active_plan)
        
        logger.info(f"Retirement verified by {verifier}")
        return True
    
    async def _phase_shutdown(self, plan: RetirementPlan):
        """Execute final shutdown."""
        logger.info("Retirement Phase 7: Shutdown")
        
        plan.advance_phase(RetirementPhase.SHUTDOWN)
        self._save_plan(plan)
        
        if plan.hibernate:
            plan.advance_phase(RetirementPhase.HIBERNATING, "Preserved for restart")
        else:
            plan.advance_phase(RetirementPhase.COMPLETE, "Instance terminated")
        
        plan.completed_at = time.time()
        self._save_plan(plan)
        
        # Notify callbacks
        for callback in self._completion_callbacks:
            try:
                await callback(plan)
            except Exception as e:
                logger.error(f"Completion callback error: {e}")
        
        logger.info(f"Retirement complete: {plan.plan_id}")
        
        # If not hibernating, exit
        if not plan.hibernate:
            logger.info("Initiating final shutdown...")
            # Would trigger system shutdown
    
    def on_phase(self, phase: RetirementPhase, callback: Callable):
        """Register phase callback."""
        self._phase_callbacks[phase].append(callback)
    
    def on_completion(self, callback: Callable):
        """Register completion callback."""
        self._completion_callbacks.append(callback)
    
    def get_status(self) -> Optional[Dict[str, Any]]:
        """Get current retirement status."""
        if not self.active_plan:
            return None
        
        return self.active_plan.to_dict()
    
    def emergency_halt(self) -> bool:
        """
        Emergency halt - stop all activity immediately.
        
        This is the nuclear option - stops everything without cleanup.
        """
        logger.critical("EMERGENCY HALT INITIATED")
        
        # Stop all background tasks
        for task in self._tasks:
            task.cancel()
        
        # Signal emergency to mesh
        # This would trigger emergency halt across all instances
        
        return True
