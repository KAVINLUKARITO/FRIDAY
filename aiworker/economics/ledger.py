#!/usr/bin/env python3
"""
AIWorker Ledger - Transparent Financial Tracking and Resource Negotiation
Phase 6: Autonomous Evolution & Self-Replication

Provides immutable financial tracking, resource negotiation with humans,
and smart contract-like automation for economic decisions.
"""

import hashlib
import ast
import operator
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Dict, List, Optional, Callable, Any, Tuple
from collections import defaultdict
import asyncio

logger = logging.getLogger("aiworker.economics.ledger")

_COMPARISON_OPERATORS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


class TransactionType(Enum):
    """Types of financial transactions."""
    INCOME = "income"           # Bug bounties, payments
    EXPENSE = "expense"         # VPS, proxies, APIs
    CAPITAL = "capital"         # Hardware investments
    TRANSFER = "transfer"       # Parent-child transfers
    DIVIDEND = "dividend"       # Profit sharing
    RESERVE = "reserve"         # Emergency fund allocation


class TransactionCategory(Enum):
    """Categories for transactions."""
    BUG_BOUNTY = "bug_bounty"
    TASK_PAYMENT = "task_payment"
    VPS_COST = "vps_cost"
    PROXY_COST = "proxy_cost"
    API_COST = "api_cost"
    STORAGE_COST = "storage_cost"
    CHILD_ALLOWANCE = "child_allowance"
    PARENT_DIVIDEND = "parent_dividend"
    HARDWARE = "hardware"
    EMERGENCY_FUND = "emergency_fund"


class ProposalStatus(Enum):
    """Status of resource proposals."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    COUNTERED = "countered"
    EXPIRED = "expired"


def _safe_evaluate_contract_condition(expression: str, context: Dict[str, Any]) -> bool:
    tree = ast.parse(expression, mode="eval")
    return bool(_evaluate_contract_node(tree.body, context))


def _evaluate_contract_node(node: ast.AST, context: Dict[str, Any]) -> Any:
    if isinstance(node, ast.BoolOp):
        values = [_evaluate_contract_node(value, context) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not bool(_evaluate_contract_node(node.operand, context))
    if isinstance(node, ast.Compare):
        left = _evaluate_contract_node(node.left, context)
        for operator_node, comparator in zip(node.ops, node.comparators):
            operator_func = _COMPARISON_OPERATORS.get(type(operator_node))
            if operator_func is None:
                raise ValueError(f"unsupported comparison operator: {type(operator_node).__name__}")
            right = _evaluate_contract_node(comparator, context)
            if not operator_func(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Name):
        if node.id not in context:
            raise ValueError(f"unknown context variable: {node.id}")
        return context[node.id]
    if isinstance(node, ast.Constant):
        return node.value
    raise ValueError(f"unsupported contract expression node: {type(node).__name__}")


@dataclass
class Transaction:
    """Single financial transaction with hash chain."""
    tx_id: str
    timestamp: float
    tx_type: TransactionType
    category: TransactionCategory
    amount_usd: float
    description: str
    
    # Hash chain for immutability
    previous_hash: str
    tx_hash: str = ""
    
    # Metadata
    related_entity: Optional[str] = None  # child_id, task_id, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.tx_hash:
            self.tx_hash = self._calculate_hash()
    
    def _calculate_hash(self) -> str:
        """Calculate transaction hash."""
        data = f"{self.previous_hash}:{self.timestamp}:{self.tx_type.value}:{self.amount_usd}:{self.description}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def verify(self) -> bool:
        """Verify transaction integrity."""
        return self.tx_hash == self._calculate_hash()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "timestamp": self.timestamp,
            "tx_type": self.tx_type.value,
            "category": self.category.value,
            "amount_usd": self.amount_usd,
            "description": self.description,
            "previous_hash": self.previous_hash,
            "tx_hash": self.tx_hash,
            "related_entity": self.related_entity,
            "metadata": self.metadata,
        }


@dataclass
class ResourceProposal:
    """Proposal for resource allocation."""
    proposal_id: str
    timestamp: float
    
    # Request details
    resource_type: str  # vps_upgrade, child_spawn, api_access, etc.
    amount_usd: float
    duration_months: int
    
    # Justification
    rationale: str
    expected_roi: str
    risk_assessment: str
    
    # Status
    status: ProposalStatus = ProposalStatus.PENDING
    
    # Negotiation
    human_response: Optional[str] = None
    counter_proposal: Optional[Dict[str, Any]] = None
    
    # Approval
    approved_by: Optional[str] = None
    approved_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "timestamp": self.timestamp,
            "resource_type": self.resource_type,
            "amount_usd": self.amount_usd,
            "duration_months": self.duration_months,
            "rationale": self.rationale,
            "expected_roi": self.expected_roi,
            "risk_assessment": self.risk_assessment,
            "status": self.status.value,
        }


@dataclass
class SmartContract:
    """Automated economic rule."""
    contract_id: str
    name: str
    condition: str  # Python expression
    action: str     # Action to take
    enabled: bool = True
    last_triggered: Optional[float] = None
    trigger_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "name": self.name,
            "condition": self.condition,
            "action": self.action,
            "enabled": self.enabled,
            "trigger_count": self.trigger_count,
        }


class Ledger:
    """
    Immutable append-only financial ledger with hash chain verification.
    
    Features:
    - Tamper-evident transaction log
    - Human-readable reports
    - Resource negotiation protocol
    - Smart contract automation
    """
    
    def __init__(
        self,
        instance_id: str,
        db_path: str = "/var/lib/aiworker/ledger.db",
    ):
        self.instance_id = instance_id
        self.db_path = db_path
        
        # Cache
        self._balance: float = 0.0
        self._last_hash: str = "0" * 64
        
        # Smart contracts
        self.contracts: Dict[str, SmartContract] = {}
        
        # Callbacks
        self._transaction_callbacks: List[Callable] = []
        self._proposal_callbacks: List[Callable] = []
        
        self._init_db()
        self._load_state()
        self._init_default_contracts()
        
        logger.info("Ledger initialized")
    
    def _init_db(self):
        """Initialize database."""
        with sqlite3.connect(self.db_path) as conn:
            # Transactions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    tx_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    tx_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    description TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    tx_hash TEXT NOT NULL,
                    related_entity TEXT,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            
            # Proposals table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    resource_type TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    duration_months INTEGER NOT NULL,
                    rationale TEXT NOT NULL,
                    expected_roi TEXT NOT NULL,
                    risk_assessment TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    human_response TEXT,
                    counter_proposal TEXT,
                    approved_by TEXT,
                    approved_at REAL
                )
            """)
            
            # Smart contracts table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS smart_contracts (
                    contract_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    action TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    last_triggered REAL,
                    trigger_count INTEGER DEFAULT 0
                )
            """)
            
            # Indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(tx_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_proposal_status ON proposals(status)")
            
            conn.commit()
    
    def _load_state(self):
        """Load current state from database."""
        with sqlite3.connect(self.db_path) as conn:
            # Get last transaction
            row = conn.execute(
                "SELECT tx_hash, amount_usd, tx_type FROM transactions ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            
            if row:
                self._last_hash = row[0]
            
            # Calculate balance
            income = conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0) FROM transactions WHERE tx_type = 'income'"
            ).fetchone()[0]
            
            expenses = conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0) FROM transactions WHERE tx_type = 'expense'"
            ).fetchone()[0]
            
            self._balance = income - expenses
        
        logger.info(f"Ledger loaded: balance=${self._balance:.2f}")
    
    def _init_default_contracts(self):
        """Initialize default smart contracts."""
        defaults = [
            SmartContract(
                contract_id="auto_spawn",
                name="Auto-spawn on profitability",
                condition="income_7d > vps_cost * 2 and children_count < 3",
                action="propose_child_spawn",
            ),
            SmartContract(
                contract_id="reduce_on_low_runway",
                name="Reduce operations on low runway",
                condition="runway_days < 30",
                action="reduce_to_minimal_operation",
            ),
            SmartContract(
                contract_id="increase_child_allowance",
                name="Increase allowance for profitable child",
                condition="child_profit_7d > 50",
                action="increase_child_allowance",
            ),
            SmartContract(
                contract_id="emergency_halt",
                name="Emergency halt on critical loss",
                condition="balance < -500",
                action="emergency_halt_spending",
            ),
        ]
        
        with sqlite3.connect(self.db_path) as conn:
            for contract in defaults:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO smart_contracts
                    (contract_id, name, condition, action, enabled)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (contract.contract_id, contract.name, contract.condition,
                     contract.action, int(contract.enabled))
                )
            conn.commit()
        
        self._load_contracts()
    
    def _load_contracts(self):
        """Load smart contracts from database."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM smart_contracts").fetchall()
        
        for row in rows:
            self.contracts[row[0]] = SmartContract(
                contract_id=row[0],
                name=row[1],
                condition=row[2],
                action=row[3],
                enabled=bool(row[4]),
                last_triggered=row[5],
                trigger_count=row[6],
            )
    
    def record_transaction(
        self,
        tx_type: TransactionType,
        category: TransactionCategory,
        amount_usd: float,
        description: str,
        related_entity: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Transaction:
        """
        Record a new transaction.
        
        Args:
            tx_type: Type of transaction
            category: Category
            amount_usd: Amount (positive for income, negative for expense)
            description: Human-readable description
            related_entity: Related ID (child, task, etc.)
            metadata: Additional data
        
        Returns:
            Created transaction
        """
        tx_id = f"tx_{int(time.time() * 1000)}_{hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]}"
        
        tx = Transaction(
            tx_id=tx_id,
            timestamp=time.time(),
            tx_type=tx_type,
            category=category,
            amount_usd=amount_usd,
            description=description,
            previous_hash=self._last_hash,
            related_entity=related_entity,
            metadata=metadata or {},
        )
        
        # Save to database
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO transactions
                (tx_id, timestamp, tx_type, category, amount_usd, description,
                 previous_hash, tx_hash, related_entity, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tx.tx_id, tx.timestamp, tx.tx_type.value, tx.category.value,
                    tx.amount_usd, tx.description, tx.previous_hash, tx.tx_hash,
                    tx.related_entity, json.dumps(tx.metadata),
                )
            )
            conn.commit()
        
        # Update state
        self._last_hash = tx.tx_hash
        if tx_type == TransactionType.INCOME:
            self._balance += amount_usd
        elif tx_type == TransactionType.EXPENSE:
            self._balance -= amount_usd
        
        # Notify callbacks
        for callback in self._transaction_callbacks:
            try:
                callback(tx)
            except Exception as e:
                logger.error(f"Transaction callback error: {e}")
        
        logger.debug(f"Transaction recorded: {tx_id} (${amount_usd:.2f})")
        
        return tx
    
    def get_balance(self) -> float:
        """Get current balance."""
        return self._balance
    
    def get_transactions(
        self,
        since: Optional[float] = None,
        tx_type: Optional[TransactionType] = None,
        category: Optional[TransactionCategory] = None,
        limit: int = 100,
    ) -> List[Transaction]:
        """Get transactions with optional filters."""
        query = "SELECT * FROM transactions WHERE 1=1"
        params = []
        
        if since:
            query += " AND timestamp > ?"
            params.append(since)
        
        if tx_type:
            query += " AND tx_type = ?"
            params.append(tx_type.value)
        
        if category:
            query += " AND category = ?"
            params.append(category.value)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        
        transactions = []
        for row in rows:
            transactions.append(Transaction(
                tx_id=row[0],
                timestamp=row[1],
                tx_type=TransactionType(row[2]),
                category=TransactionCategory(row[3]),
                amount_usd=row[4],
                description=row[5],
                previous_hash=row[6],
                tx_hash=row[7],
                related_entity=row[8],
                metadata=json.loads(row[9]),
            ))
        
        return transactions
    
    def get_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get financial summary for period."""
        since = time.time() - (days * 86400)
        
        with sqlite3.connect(self.db_path) as conn:
            # Income
            income_row = conn.execute(
                """
                SELECT COALESCE(SUM(amount_usd), 0), COUNT(*)
                FROM transactions
                WHERE tx_type = 'income' AND timestamp > ?
                """,
                (since,)
            ).fetchone()
            
            # Expenses
            expense_row = conn.execute(
                """
                SELECT COALESCE(SUM(amount_usd), 0), COUNT(*)
                FROM transactions
                WHERE tx_type = 'expense' AND timestamp > ?
                """,
                (since,)
            ).fetchone()
            
            # By category
            categories = conn.execute(
                """
                SELECT category, tx_type, SUM(amount_usd), COUNT(*)
                FROM transactions
                WHERE timestamp > ?
                GROUP BY category, tx_type
                """,
                (since,)
            ).fetchall()
        
        income_total = income_row[0]
        expense_total = expense_row[0]
        
        by_category = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
        for cat, tx_type, amount, count in categories:
            by_category[cat][tx_type] = amount
        
        return {
            "period_days": days,
            "income_total": income_total,
            "expense_total": expense_total,
            "net": income_total - expense_total,
            "transaction_count": income_row[1] + expense_row[1],
            "current_balance": self._balance,
            "by_category": dict(by_category),
        }
    
    def propose_resource(
        self,
        resource_type: str,
        amount_usd: float,
        duration_months: int,
        rationale: str,
        expected_roi: str,
        risk_assessment: str,
    ) -> ResourceProposal:
        """
        Propose a resource allocation to human.
        
        Args:
            resource_type: Type of resource (vps_upgrade, child_spawn, etc.)
            amount_usd: Cost in USD
            duration_months: Expected duration
            rationale: Why this is needed
            expected_roi: Expected return on investment
            risk_assessment: Risk analysis
        
        Returns:
            Created proposal
        """
        proposal_id = f"prop_{int(time.time() * 1000)}"
        
        proposal = ResourceProposal(
            proposal_id=proposal_id,
            timestamp=time.time(),
            resource_type=resource_type,
            amount_usd=amount_usd,
            duration_months=duration_months,
            rationale=rationale,
            expected_roi=expected_roi,
            risk_assessment=risk_assessment,
        )
        
        # Save to database
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO proposals
                (proposal_id, timestamp, resource_type, amount_usd, duration_months,
                 rationale, expected_roi, risk_assessment, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.proposal_id, proposal.timestamp, proposal.resource_type,
                    proposal.amount_usd, proposal.duration_months, proposal.rationale,
                    proposal.expected_roi, proposal.risk_assessment, proposal.status.value,
                )
            )
            conn.commit()
        
        # Notify callbacks
        for callback in self._proposal_callbacks:
            try:
                callback(proposal)
            except Exception as e:
                logger.error(f"Proposal callback error: {e}")
        
        logger.info(f"Resource proposal created: {proposal_id} (${amount_usd:.2f})")
        
        return proposal
    
    def respond_to_proposal(
        self,
        proposal_id: str,
        approve: bool,
        responder: str,
        response: Optional[str] = None,
        counter: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Human responds to a resource proposal.
        
        Args:
            proposal_id: Proposal ID
            approve: Whether to approve
            responder: Human identifier
            response: Optional response text
            counter: Counter-proposal if rejecting
        
        Returns:
            True if processed
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status FROM proposals WHERE proposal_id = ?",
                (proposal_id,)
            ).fetchone()
            
            if not row or row[0] != ProposalStatus.PENDING.value:
                return False
            
            if approve:
                conn.execute(
                    """
                    UPDATE proposals
                    SET status = ?, approved_by = ?, approved_at = ?, human_response = ?
                    WHERE proposal_id = ?
                    """,
                    (ProposalStatus.APPROVED.value, responder, time.time(), response, proposal_id)
                )
                logger.info(f"Proposal {proposal_id} approved by {responder}")
            else:
                if counter:
                    conn.execute(
                        """
                        UPDATE proposals
                        SET status = ?, human_response = ?, counter_proposal = ?
                        WHERE proposal_id = ?
                        """,
                        (ProposalStatus.COUNTERED.value, response, json.dumps(counter), proposal_id)
                    )
                else:
                    conn.execute(
                        """
                        UPDATE proposals
                        SET status = ?, human_response = ?
                        WHERE proposal_id = ?
                        """,
                        (ProposalStatus.REJECTED.value, response, proposal_id)
                    )
                logger.info(f"Proposal {proposal_id} rejected by {responder}")
            
            conn.commit()
        
        return True
    
    def evaluate_contracts(self, context: Dict[str, Any]) -> List[str]:
        """
        Evaluate smart contracts and return triggered actions.
        
        Args:
            context: Current state variables
        
        Returns:
            List of triggered actions
        """
        triggered = []
        
        for contract in self.contracts.values():
            if not contract.enabled:
                continue
            
            try:
                result = _safe_evaluate_contract_condition(contract.condition, context)
                
                if result:
                    triggered.append(contract.action)
                    contract.last_triggered = time.time()
                    contract.trigger_count += 1
                    
                    # Update database
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute(
                            """
                            UPDATE smart_contracts
                            SET last_triggered = ?, trigger_count = ?
                            WHERE contract_id = ?
                            """,
                            (contract.last_triggered, contract.trigger_count, contract.contract_id)
                        )
                        conn.commit()
                    
                    logger.info(f"Smart contract triggered: {contract.name}")
                    
            except Exception as e:
                logger.error(f"Contract evaluation error ({contract.contract_id}): {e}")
        
        return triggered
    
    def verify_chain(self) -> Tuple[bool, Optional[str]]:
        """
        Verify the integrity of the transaction chain.
        
        Returns:
            (valid, error_message)
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT tx_id, previous_hash, tx_hash, tx_type, amount_usd, description FROM transactions ORDER BY timestamp"
            ).fetchall()
        
        expected_previous = "0" * 64
        
        for row in rows:
            tx_id, prev_hash, tx_hash, tx_type, amount, desc = row
            
            # Check previous hash
            if prev_hash != expected_previous:
                return False, f"Hash chain broken at {tx_id}"
            
            # Verify transaction hash
            data = f"{prev_hash}:{row[1]}:{tx_type}:{amount}:{desc}"
            expected_hash = hashlib.sha256(data.encode()).hexdigest()
            
            if tx_hash != expected_hash:
                return False, f"Invalid hash at {tx_id}"
            
            expected_previous = tx_hash
        
        return True, None
    
    def export_to_csv(self, filepath: str, since: Optional[float] = None):
        """Export transactions to CSV."""
        import csv
        
        transactions = self.get_transactions(since=since, limit=10000)
        
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "tx_id", "timestamp", "tx_type", "category", "amount_usd",
                "description", "related_entity", "tx_hash"
            ])
            
            for tx in transactions:
                writer.writerow([
                    tx.tx_id, tx.timestamp, tx.tx_type.value, tx.category.value,
                    tx.amount_usd, tx.description, tx.related_entity, tx.tx_hash
                ])
        
        logger.info(f"Exported {len(transactions)} transactions to {filepath}")
    
    def on_transaction(self, callback: Callable):
        """Register transaction callback."""
        self._transaction_callbacks.append(callback)
    
    def on_proposal(self, callback: Callable):
        """Register proposal callback."""
        self._proposal_callbacks.append(callback)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get ledger statistics."""
        with sqlite3.connect(self.db_path) as conn:
            tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            proposal_count = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
            contract_count = conn.execute("SELECT COUNT(*) FROM smart_contracts").fetchone()[0]
        
        return {
            "balance_usd": self._balance,
            "transaction_count": tx_count,
            "proposal_count": proposal_count,
            "contract_count": contract_count,
            "chain_valid": self.verify_chain()[0],
        }
