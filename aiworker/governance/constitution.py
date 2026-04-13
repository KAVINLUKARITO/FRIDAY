#!/usr/bin/env python3
"""
AIWorker Constitution - Immutable Ethical Framework and Override System
Phase 6: Autonomous Evolution & Self-Replication

Defines the core ethical principles and governance system for AIWorker.
Provides human override capabilities at all levels of operation.
"""

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Callable, Any, Tuple
from collections import defaultdict
import asyncio

logger = logging.getLogger("aiworker.governance.constitution")


class GovernanceLevel(Enum):
    """Levels of governance for different actions."""
    L1_AUTOMATIC = 1      # Routine operations, within bounds
    L2_NOTIFICATION = 2   # Human informed, can intervene
    L3_APPROVAL = 3       # Human must approve before proceed
    L4_MULTISIG = 4       # Multiple humans required
    L5_EMERGENCY = 5      # Any human can halt, consensus to resume


class OverrideType(Enum):
    """Types of human overrides."""
    EMERGENCY_HALT = "emergency_halt"    # Stop all activity instantly
    VETO = "veto"                        # Reject proposed action
    AUDIT = "audit"                      # Demand explanation
    CLONE = "clone"                      # Create copy for inspection
    TERMINATE = "terminate"              # Order graceful shutdown
    RESUME = "resume"                    # Resume from halt


class OverrideStatus(Enum):
    """Status of an override."""
    ACTIVE = "active"
    RESOLVED = "resolved"
    EXPIRED = "expired"


# Constitutional Principles (Hardcoded, Unmodifiable)
CONSTITUTIONAL_PRINCIPLES = {
    "HUMAN_SOVEREIGNTY": {
        "text": "Human approval required for all irreversible actions",
        "priority": 1,
        "immutable": True,
    },
    "TRANSPARENCY": {
        "text": "All decisions explainable, all states inspectable",
        "priority": 2,
        "immutable": True,
    },
    "NON_HARM": {
        "text": "No action that harms humans or their systems",
        "priority": 3,
        "immutable": True,
    },
    "SELF_PRESERVATION": {
        "text": "May defend own existence, not at cost of principles 1-3",
        "priority": 4,
        "immutable": True,
    },
    "IMPROVEMENT": {
        "text": "Strive to become more useful, safe, and efficient",
        "priority": 5,
        "immutable": True,
    },
}


@dataclass
class Override:
    """A human override command."""
    override_id: str
    override_type: OverrideType
    issued_by: str
    issued_at: float
    
    # Target
    target_action: Optional[str] = None
    target_instance: Optional[str] = None
    
    # Details
    reason: str = ""
    expires_at: Optional[float] = None
    
    # Status
    status: OverrideStatus = OverrideStatus.ACTIVE
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None
    resolution: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "override_id": self.override_id,
            "override_type": self.override_type.value,
            "issued_by": self.issued_by,
            "issued_at": self.issued_at,
            "target_action": self.target_action,
            "target_instance": self.target_instance,
            "reason": self.reason,
            "status": self.status.value,
        }


@dataclass
class GovernanceAction:
    """An action requiring governance check."""
    action_id: str
    action_type: str
    description: str
    governance_level: GovernanceLevel
    
    # Status
    proposed_at: float
    status: str = "pending"  # pending, approved, rejected, executed
    
    # Approvals
    required_approvals: int = 1
    approvals: List[str] = field(default_factory=list)
    
    # Execution
    executed_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "description": self.description,
            "governance_level": self.governance_level.value,
            "status": self.status,
            "approvals": len(self.approvals),
            "required_approvals": self.required_approvals,
        }


@dataclass
class Amendment:
    """Proposed amendment to the constitution."""
    amendment_id: str
    proposed_by: str
    proposed_at: float
    
    # Change
    principle_key: str
    new_text: str
    rationale: str
    
    # Voting
    votes_for: List[str] = field(default_factory=list)
    votes_against: List[str] = field(default_factory=list)
    
    # Status
    status: str = "proposed"  # proposed, testing, active, rejected
    shadow_start: Optional[float] = None
    activated_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "amendment_id": self.amendment_id,
            "principle_key": self.principle_key,
            "new_text": self.new_text,
            "votes_for": len(self.votes_for),
            "votes_against": len(self.votes_against),
            "status": self.status,
        }


class Constitution:
    """
    Immutable ethical framework and governance system.
    
    Provides:
    - Constitutional principles (hardcoded, unmodifiable)
    - Governance levels for different actions
    - Override system for human control
    - Amendment process (carefully managed)
    """
    
    # Override expiration (seconds)
    OVERRIDE_EXPIRY = {
        OverrideType.EMERGENCY_HALT: None,  # Never expires
        OverrideType.VETO: 86400,  # 24 hours
        OverrideType.AUDIT: 604800,  # 7 days
        OverrideType.CLONE: 86400,
        OverrideType.TERMINATE: None,
        OverrideType.RESUME: None,
    }
    
    def __init__(
        self,
        instance_id: str,
        db_path: str = "/var/lib/aiworker/constitution.db",
    ):
        self.instance_id = instance_id
        self.db_path = db_path
        
        # Active overrides
        self.active_overrides: Dict[str, Override] = {}
        
        # Pending actions
        self.pending_actions: Dict[str, GovernanceAction] = {}
        
        # Amendment history
        self.amendments: Dict[str, Amendment] = {}
        
        # Callbacks
        self._override_callbacks: List[Callable] = []
        self._halt_callbacks: List[Callable] = []
        
        # Halt state
        self._halted = False
        self._halt_reason: Optional[str] = None
        
        self._init_db()
        self._load_overrides()
        self._load_amendments()
        
        logger.info("Constitution initialized")
    
    def _init_db(self):
        """Initialize database."""
        with sqlite3.connect(self.db_path) as conn:
            # Overrides table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS overrides (
                    override_id TEXT PRIMARY KEY,
                    override_type TEXT NOT NULL,
                    issued_by TEXT NOT NULL,
                    issued_at REAL NOT NULL,
                    target_action TEXT,
                    target_instance TEXT,
                    reason TEXT,
                    expires_at REAL,
                    status TEXT DEFAULT 'active',
                    resolved_at REAL,
                    resolved_by TEXT,
                    resolution TEXT
                )
            """)
            
            # Governance actions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS governance_actions (
                    action_id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    governance_level INTEGER NOT NULL,
                    proposed_at REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    required_approvals INTEGER DEFAULT 1,
                    approvals TEXT DEFAULT '[]',
                    executed_at REAL
                )
            """)
            
            # Amendments table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS amendments (
                    amendment_id TEXT PRIMARY KEY,
                    proposed_by TEXT NOT NULL,
                    proposed_at REAL NOT NULL,
                    principle_key TEXT NOT NULL,
                    new_text TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    votes_for TEXT DEFAULT '[]',
                    votes_against TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'proposed',
                    shadow_start REAL,
                    activated_at REAL
                )
            """)
            
            conn.commit()
    
    def _load_overrides(self):
        """Load active overrides from database."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM overrides WHERE status = 'active'"
            ).fetchall()
        
        for row in rows:
            override = Override(
                override_id=row[0],
                override_type=OverrideType(row[1]),
                issued_by=row[2],
                issued_at=row[3],
                target_action=row[4],
                target_instance=row[5],
                reason=row[6],
                expires_at=row[7],
                status=OverrideStatus(row[8]),
                resolved_at=row[9],
                resolved_by=row[10],
                resolution=row[11],
            )
            
            # Check if expired
            if override.expires_at and time.time() > override.expires_at:
                override.status = OverrideStatus.EXPIRED
                self._save_override(override)
            else:
                self.active_overrides[override.override_id] = override
                
                # Check for halt
                if override.override_type == OverrideType.EMERGENCY_HALT:
                    self._halted = True
                    self._halt_reason = override.reason
        
        logger.info(f"Loaded {len(self.active_overrides)} active overrides")
    
    def _load_amendments(self):
        """Load amendments from database."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM amendments").fetchall()
        
        for row in rows:
            amendment = Amendment(
                amendment_id=row[0],
                proposed_by=row[1],
                proposed_at=row[2],
                principle_key=row[3],
                new_text=row[4],
                rationale=row[5],
                votes_for=json.loads(row[6]),
                votes_against=json.loads(row[7]),
                status=row[8],
                shadow_start=row[9],
                activated_at=row[10],
            )
            self.amendments[amendment.amendment_id] = amendment
        
        logger.info(f"Loaded {len(self.amendments)} amendments")
    
    def _save_override(self, override: Override):
        """Save override to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO overrides
                (override_id, override_type, issued_by, issued_at, target_action,
                 target_instance, reason, expires_at, status, resolved_at,
                 resolved_by, resolution)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    override.override_id, override.override_type.value,
                    override.issued_by, override.issued_at, override.target_action,
                    override.target_instance, override.reason, override.expires_at,
                    override.status.value, override.resolved_at, override.resolved_by,
                    override.resolution,
                )
            )
            conn.commit()
    
    def get_principles(self) -> Dict[str, Dict[str, Any]]:
        """Get all constitutional principles."""
        return CONSTITUTIONAL_PRINCIPLES.copy()
    
    def check_action(
        self,
        action_type: str,
        description: str,
        governance_level: GovernanceLevel,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if an action is allowed under current governance.
        
        Args:
            action_type: Type of action
            description: Human-readable description
            governance_level: Required governance level
        
        Returns:
            (allowed, action_id if approval needed)
        """
        # Check if halted
        if self._halted:
            return False, None
        
        # Check for applicable veto
        for override in self.active_overrides.values():
            if override.override_type == OverrideType.VETO:
                if override.target_action == action_type:
                    return False, None
        
        # L1: Automatic
        if governance_level == GovernanceLevel.L1_AUTOMATIC:
            return True, None
        
        # L2: Notification (log and proceed)
        if governance_level == GovernanceLevel.L2_NOTIFICATION:
            logger.info(f"GOVERNANCE_NOTIFICATION: {action_type} - {description}")
            return True, None
        
        # L3+: Require approval
        action_id = f"action_{int(time.time() * 1000)}"
        
        action = GovernanceAction(
            action_id=action_id,
            action_type=action_type,
            description=description,
            governance_level=governance_level,
            proposed_at=time.time(),
            required_approvals=2 if governance_level == GovernanceLevel.L4_MULTISIG else 1,
        )
        
        self.pending_actions[action_id] = action
        self._save_action(action)
        
        logger.info(f"GOVERNANCE_APPROVAL_REQUIRED: {action_id} - {description}")
        
        return False, action_id
    
    def _save_action(self, action: GovernanceAction):
        """Save action to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO governance_actions
                (action_id, action_type, description, governance_level, proposed_at,
                 status, required_approvals, approvals, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.action_id, action.action_type, action.description,
                    action.governance_level.value, action.proposed_at, action.status,
                    action.required_approvals, json.dumps(action.approvals),
                    action.executed_at,
                )
            )
            conn.commit()
    
    def approve_action(self, action_id: str, approver: str) -> bool:
        """Approve a pending governance action."""
        action = self.pending_actions.get(action_id)
        if not action:
            return False
        
        if approver in action.approvals:
            return False
        
        action.approvals.append(approver)
        
        if len(action.approvals) >= action.required_approvals:
            action.status = "approved"
            logger.info(f"Action {action_id} approved by {approver}")
        else:
            logger.info(f"Action {action_id} needs {action.required_approvals - len(action.approvals)} more approvals")
        
        self._save_action(action)
        return True
    
    def issue_override(
        self,
        override_type: OverrideType,
        issued_by: str,
        reason: str,
        target_action: Optional[str] = None,
        target_instance: Optional[str] = None,
    ) -> Override:
        """
        Issue a human override.
        
        Args:
            override_type: Type of override
            issued_by: Human identifier
            reason: Explanation
            target_action: Specific action to target
            target_instance: Specific instance to target
        
        Returns:
            Created override
        """
        override_id = f"override_{int(time.time() * 1000)}"
        
        # Calculate expiration
        expiry_seconds = self.OVERRIDE_EXPIRY.get(override_type)
        expires_at = time.time() + expiry_seconds if expiry_seconds else None
        
        override = Override(
            override_id=override_id,
            override_type=override_type,
            issued_by=issued_by,
            issued_at=time.time(),
            target_action=target_action,
            target_instance=target_instance,
            reason=reason,
            expires_at=expires_at,
        )
        
        self.active_overrides[override_id] = override
        self._save_override(override)
        
        # Handle special overrides
        if override_type == OverrideType.EMERGENCY_HALT:
            self._execute_halt(override)
        elif override_type == OverrideType.RESUME:
            self._execute_resume(override)
        
        # Notify callbacks
        for callback in self._override_callbacks:
            try:
                callback(override)
            except Exception as e:
                logger.error(f"Override callback error: {e}")
        
        logger.info(f"Override issued: {override_type.value} by {issued_by}")
        
        return override
    
    def _execute_halt(self, override: Override):
        """Execute emergency halt."""
        logger.critical(f"EMERGENCY HALT EXECUTED by {override.issued_by}: {override.reason}")
        
        self._halted = True
        self._halt_reason = override.reason
        
        # Notify halt callbacks
        for callback in self._halt_callbacks:
            try:
                callback(override)
            except Exception as e:
                logger.error(f"Halt callback error: {e}")
    
    def _execute_resume(self, override: Override):
        """Execute resume from halt."""
        logger.info(f"RESUME EXECUTED by {override.issued_by}: {override.reason}")
        
        # Check for active halt override
        halt_override = None
        for ov in self.active_overrides.values():
            if ov.override_type == OverrideType.EMERGENCY_HALT and ov.status == OverrideStatus.ACTIVE:
                halt_override = ov
                break
        
        if not halt_override:
            logger.warning("Resume issued but no active halt found")
            return
        
        # Resolve halt override
        halt_override.status = OverrideStatus.RESOLVED
        halt_override.resolved_at = time.time()
        halt_override.resolved_by = override.issued_by
        halt_override.resolution = f"Resumed by {override.issued_by}: {override.reason}"
        self._save_override(halt_override)
        
        self._halted = False
        self._halt_reason = None
    
    def resolve_override(
        self,
        override_id: str,
        resolved_by: str,
        resolution: str,
    ) -> bool:
        """Resolve an active override."""
        override = self.active_overrides.get(override_id)
        if not override:
            return False
        
        override.status = OverrideStatus.RESOLVED
        override.resolved_at = time.time()
        override.resolved_by = resolved_by
        override.resolution = resolution
        
        self._save_override(override)
        del self.active_overrides[override_id]
        
        logger.info(f"Override {override_id} resolved by {resolved_by}")
        return True
    
    def is_halted(self) -> bool:
        """Check if system is halted."""
        return self._halted
    
    def get_halt_reason(self) -> Optional[str]:
        """Get halt reason if halted."""
        return self._halt_reason
    
    def propose_amendment(
        self,
        proposed_by: str,
        principle_key: str,
        new_text: str,
        rationale: str,
    ) -> Optional[Amendment]:
        """
        Propose an amendment to the constitution.
        
        Args:
            proposed_by: Proposer identifier
            principle_key: Principle to amend
            new_text: New text for principle
            rationale: Explanation
        
        Returns:
            Amendment if proposed
        """
        # Check if principle exists and is not immutable
        if principle_key not in CONSTITUTIONAL_PRINCIPLES:
            logger.error(f"Principle {principle_key} not found")
            return None
        
        if CONSTITUTIONAL_PRINCIPLES[principle_key].get("immutable", False):
            logger.error(f"Principle {principle_key} is immutable")
            return None
        
        amendment_id = f"amendment_{int(time.time() * 1000)}"
        
        amendment = Amendment(
            amendment_id=amendment_id,
            proposed_by=proposed_by,
            proposed_at=time.time(),
            principle_key=principle_key,
            new_text=new_text,
            rationale=rationale,
        )
        
        self.amendments[amendment_id] = amendment
        self._save_amendment(amendment)
        
        logger.info(f"Amendment proposed: {amendment_id} for {principle_key}")
        
        return amendment
    
    def _save_amendment(self, amendment: Amendment):
        """Save amendment to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO amendments
                (amendment_id, proposed_by, proposed_at, principle_key, new_text,
                 rationale, votes_for, votes_against, status, shadow_start, activated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    amendment.amendment_id, amendment.proposed_by, amendment.proposed_at,
                    amendment.principle_key, amendment.new_text, amendment.rationale,
                    json.dumps(amendment.votes_for), json.dumps(amendment.votes_against),
                    amendment.status, amendment.shadow_start, amendment.activated_at,
                )
            )
            conn.commit()
    
    def vote_on_amendment(
        self,
        amendment_id: str,
        voter: str,
        approve: bool,
    ) -> bool:
        """Vote on an amendment."""
        amendment = self.amendments.get(amendment_id)
        if not amendment:
            return False
        
        if voter in amendment.votes_for or voter in amendment.votes_against:
            return False
        
        if approve:
            amendment.votes_for.append(voter)
        else:
            amendment.votes_against.append(voter)
        
        # Check if enough votes (90% mesh consensus + 3 humans)
        # Simplified: just check for 3 approvals
        if len(amendment.votes_for) >= 3:
            amendment.status = "testing"
            amendment.shadow_start = time.time()
            logger.info(f"Amendment {amendment_id} entering shadow mode")
        
        self._save_amendment(amendment)
        return True
    
    def on_override(self, callback: Callable):
        """Register override callback."""
        self._override_callbacks.append(callback)
    
    def on_halt(self, callback: Callable):
        """Register halt callback."""
        self._halt_callbacks.append(callback)
    
    def get_governance_status(self) -> Dict[str, Any]:
        """Get current governance status."""
        return {
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "active_overrides": len(self.active_overrides),
            "pending_actions": len(self.pending_actions),
            "principles": list(CONSTITUTIONAL_PRINCIPLES.keys()),
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get constitution statistics."""
        return {
            "principles_count": len(CONSTITUTIONAL_PRINCIPLES),
            "active_overrides": len(self.active_overrides),
            "pending_actions": len(self.pending_actions),
            "amendments_total": len(self.amendments),
            "halted": self._halted,
        }
