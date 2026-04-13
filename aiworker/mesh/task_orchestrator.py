#!/usr/bin/env python3
"""
AIWorker Task Orchestrator - Distributed Task Allocation
Phase 5: Ecosystem Expansion & Multi-Instance Coordination

Coordinates task distribution across AIWorker mesh to avoid duplicate effort
and optimize resource utilization. Uses SQLite-based CRDT for distributed
ledger and implements work sharding by domain.
"""

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
import zlib
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Callable, Any, Tuple
from collections import defaultdict
import heapq
import threading

from aiworker.mesh.network_node import (
    MeshNode, MeshMessage, MessageType, NodeRole, NodeCapabilities
)

logger = logging.getLogger("aiworker.mesh.orchestrator")


class TaskType(Enum):
    """Types of tasks that can be distributed."""
    RECON = "recon"           # Subdomain enumeration
    SCAN = "scan"             # Vulnerability scanning
    ANALYZE = "analyze"       # Deep inspection
    VALIDATE = "validate"     # Safety cage review (NEVER distributed)
    REPORT = "report"         # Draft submission (local only)


class TaskStatus(Enum):
    """Task lifecycle states."""
    PENDING = "pending"       # Waiting for allocation
    BIDDING = "bidding"       # Collecting bids from nodes
    ASSIGNED = "assigned"     # Assigned to a node
    RUNNING = "running"       # Actively being executed
    COMPLETED = "completed"   # Finished successfully
    FAILED = "failed"         # Failed, may be retried
    CANCELLED = "cancelled"   # Cancelled by user/system


class TaskPriority(Enum):
    """Task priority levels."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class Task:
    """Represents a unit of work in the mesh."""
    task_id: str
    task_type: TaskType
    payload: Dict[str, Any]
    
    # Assignment
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: Optional[str] = None
    assigned_at: Optional[float] = None
    
    # Metadata
    priority: TaskPriority = TaskPriority.NORMAL
    created_by: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    
    # Execution
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    # Sharding
    shard_key: Optional[str] = None  # For work splitting
    parent_task: Optional[str] = None  # For subtasks
    
    # Estimates
    estimated_duration: float = 600.0  # seconds, default 10 min
    estimated_memory: int = 1024  # MB
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["task_type"] = self.task_type.value
        data["status"] = self.status.value
        data["priority"] = self.priority.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        data = data.copy()
        data["task_type"] = TaskType(data["task_type"])
        data["status"] = TaskStatus(data["status"])
        data["priority"] = TaskPriority(data["priority"])
        return cls(**data)
    
    def get_shard_id(self) -> str:
        """Generate shard ID for work distribution."""
        shard_data = f"{self.task_type.value}:{self.shard_key or self.task_id}"
        return hashlib.sha256(shard_data.encode()).hexdigest()[:16]


@dataclass
class TaskBid:
    """Bid from a node for a task."""
    task_id: str
    node_id: str
    bid_score: float  # Lower is better
    capabilities: Dict[str, Any]
    estimated_completion: float  # timestamp
    bid_at: float = field(default_factory=time.time)
    
    def __lt__(self, other: "TaskBid") -> bool:
        return self.bid_score < other.bid_score


@dataclass
class ShardAllocation:
    """Tracks work sharding for a domain."""
    domain: str
    total_shards: int
    shard_assignments: Dict[int, str] = field(default_factory=dict)  # shard -> node
    completed_shards: Set[int] = field(default_factory=set)
    failed_shards: Set[int] = field(default_factory=set)


class DistributedLedger:
    """
    SQLite-based CRDT for distributed task tracking.
    
    Each node maintains a local copy that syncs with peers.
    Uses vector clocks for conflict resolution.
    """
    
    def __init__(self, db_path: str, node_id: str):
        self.db_path = db_path
        self.node_id = node_id
        self._lock = threading.RLock()
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    status TEXT NOT NULL,
                    assigned_to TEXT,
                    assigned_at REAL,
                    priority INTEGER NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    started_at REAL,
                    completed_at REAL,
                    result BLOB,
                    error TEXT,
                    shard_key TEXT,
                    parent_task TEXT,
                    estimated_duration REAL,
                    estimated_memory INTEGER,
                    vector_clock TEXT NOT NULL,
                    last_modified REAL NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bids (
                    bid_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    bid_score REAL NOT NULL,
                    capabilities BLOB,
                    estimated_completion REAL NOT NULL,
                    bid_at REAL NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shard_allocations (
                    domain TEXT PRIMARY KEY,
                    total_shards INTEGER NOT NULL,
                    assignments BLOB NOT NULL,
                    completed BLOB NOT NULL,
                    failed BLOB NOT NULL,
                    vector_clock TEXT NOT NULL,
                    last_modified REAL NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_bids_task ON bids(task_id)
            """)
            
            conn.commit()
    
    def _get_vector_clock(self) -> Dict[str, int]:
        """Get current vector clock for this node."""
        return {self.node_id: int(time.time() * 1000)}
    
    def _merge_vector_clocks(
        self, 
        clock1: Dict[str, int], 
        clock2: Dict[str, int]
    ) -> Dict[str, int]:
        """Merge two vector clocks."""
        merged = clock1.copy()
        for node, ts in clock2.items():
            merged[node] = max(merged.get(node, 0), ts)
        return merged
    
    def create_task(self, task: Task) -> bool:
        """Create a new task in the ledger."""
        with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO tasks (
                            task_id, task_type, payload, status, assigned_to,
                            assigned_at, priority, created_by, created_at, expires_at,
                            started_at, completed_at, result, error, shard_key,
                            parent_task, estimated_duration, estimated_memory,
                            vector_clock, last_modified
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            task.task_id,
                            task.task_type.value,
                            zlib.compress(json.dumps(task.payload).encode()),
                            task.status.value,
                            task.assigned_to,
                            task.assigned_at,
                            task.priority.value,
                            task.created_by,
                            task.created_at,
                            task.expires_at,
                            task.started_at,
                            task.completed_at,
                            zlib.compress(json.dumps(task.result).encode()) if task.result else None,
                            task.error,
                            task.shard_key,
                            task.parent_task,
                            task.estimated_duration,
                            task.estimated_memory,
                            json.dumps(self._get_vector_clock()),
                            time.time()
                        )
                    )
                    conn.commit()
                    return True
            except sqlite3.IntegrityError:
                return False
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM tasks WHERE task_id = ?",
                    (task_id,)
                ).fetchone()
                
                if not row:
                    return None
                
                return self._row_to_task(row)
    
    def update_task_status(
        self, 
        task_id: str, 
        status: TaskStatus,
        assigned_to: Optional[str] = None,
        result: Optional[Dict] = None,
        error: Optional[str] = None
    ) -> bool:
        """Update task status."""
        with self._lock:
            updates = ["status = ?", "vector_clock = ?", "last_modified = ?"]
            params = [status.value, json.dumps(self._get_vector_clock()), time.time()]
            
            if assigned_to:
                updates.append("assigned_to = ?")
                params.append(assigned_to)
                updates.append("assigned_at = ?")
                params.append(time.time())
            
            if result:
                updates.append("result = ?")
                params.append(zlib.compress(json.dumps(result).encode()))
                updates.append("completed_at = ?")
                params.append(time.time())
            
            if error:
                updates.append("error = ?")
                params.append(error)
            
            if status == TaskStatus.RUNNING:
                updates.append("started_at = ?")
                params.append(time.time())
            
            params.append(task_id)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?",
                    params
                )
                conn.commit()
                return cursor.rowcount > 0
    
    def get_tasks_by_status(self, status: TaskStatus) -> List[Task]:
        """Get all tasks with given status."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status = ?",
                    (status.value,)
                ).fetchall()
                
                return [self._row_to_task(row) for row in rows]
    
    def get_tasks_for_node(self, node_id: str) -> List[Task]:
        """Get tasks assigned to a node."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE assigned_to = ?",
                    (node_id,)
                ).fetchall()
                
                return [self._row_to_task(row) for row in rows]
    
    def _row_to_task(self, row) -> Task:
        """Convert database row to Task."""
        return Task(
            task_id=row[0],
            task_type=TaskType(row[1]),
            payload=json.loads(zlib.decompress(row[2]).decode()),
            status=TaskStatus(row[3]),
            assigned_to=row[4],
            assigned_at=row[5],
            priority=TaskPriority(row[6]),
            created_by=row[7],
            created_at=row[8],
            expires_at=row[9],
            started_at=row[10],
            completed_at=row[11],
            result=json.loads(zlib.decompress(row[12]).decode()) if row[12] else None,
            error=row[13],
            shard_key=row[14],
            parent_task=row[15],
            estimated_duration=row[16],
            estimated_memory=row[17],
        )
    
    def add_bid(self, bid: TaskBid) -> bool:
        """Add a bid for a task."""
        with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO bids (bid_id, task_id, node_id, bid_score, 
                                        capabilities, estimated_completion, bid_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"{bid.task_id}:{bid.node_id}",
                            bid.task_id,
                            bid.node_id,
                            bid.bid_score,
                            zlib.compress(json.dumps(bid.capabilities).encode()),
                            bid.estimated_completion,
                            bid.bid_at
                        )
                    )
                    conn.commit()
                    return True
            except sqlite3.IntegrityError:
                return False
    
    def get_bids(self, task_id: str) -> List[TaskBid]:
        """Get all bids for a task."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT * FROM bids WHERE task_id = ?",
                    (task_id,)
                ).fetchall()
                
                bids = []
                for row in rows:
                    bids.append(TaskBid(
                        task_id=row[1],
                        node_id=row[2],
                        bid_score=row[3],
                        capabilities=json.loads(zlib.decompress(row[4]).decode()),
                        estimated_completion=row[5],
                        bid_at=row[6]
                    ))
                return bids
    
    def get_delta_since(self, timestamp: float) -> Dict[str, Any]:
        """Get all changes since given timestamp (for sync)."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Get updated tasks
                task_rows = conn.execute(
                    "SELECT * FROM tasks WHERE last_modified > ?",
                    (timestamp,)
                ).fetchall()
                
                tasks = [self._row_to_task(row).to_dict() for row in task_rows]
                
                # Get updated shard allocations
                shard_rows = conn.execute(
                    "SELECT * FROM shard_allocations WHERE last_modified > ?",
                    (timestamp,)
                ).fetchall()
                
                shards = []
                for row in shard_rows:
                    shards.append({
                        "domain": row[0],
                        "total_shards": row[1],
                        "assignments": json.loads(zlib.decompress(row[2]).decode()),
                        "completed": json.loads(zlib.decompress(row[3]).decode()),
                        "failed": json.loads(zlib.decompress(row[4]).decode()),
                    })
                
                return {
                    "tasks": tasks,
                    "shards": shards,
                    "timestamp": time.time()
                }
    
    def apply_delta(self, delta: Dict[str, Any]) -> int:
        """Apply sync delta from another node."""
        applied = 0
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                for task_data in delta.get("tasks", []):
                    task = Task.from_dict(task_data)
                    
                    # Check if we have this task
                    existing = conn.execute(
                        "SELECT vector_clock, last_modified FROM tasks WHERE task_id = ?",
                        (task.task_id,)
                    ).fetchone()
                    
                    if existing:
                        # Merge logic: last-write-wins for scalars
                        if task_data.get("last_modified", 0) > existing[1]:
                            conn.execute(
                                """
                                UPDATE tasks SET status = ?, assigned_to = ?, 
                                result = ?, error = ?, vector_clock = ?, last_modified = ?
                                WHERE task_id = ?
                                """,
                                (
                                    task.status.value,
                                    task.assigned_to,
                                    zlib.compress(json.dumps(task.result).encode()) if task.result else None,
                                    task.error,
                                    json.dumps(self._get_vector_clock()),
                                    time.time(),
                                    task.task_id
                                )
                            )
                            applied += 1
                    else:
                        # New task
                        self.create_task(task)
                        applied += 1
                
                conn.commit()
        
        return applied


class TaskOrchestrator:
    """
    Distributed task orchestrator for AIWorker mesh.
    
    Coordinates work distribution to avoid duplicate effort:
    1. Tasks announced to mesh
    2. Nodes bid based on capability match, load, data proximity
    3. Coordinator selects winner, broadcasts assignment
    4. Winner has exclusive lock for duration
    5. On failure, reassigns to next bidder
    """
    
    # Tasks that should never be distributed
    LOCAL_ONLY_TASKS = {TaskType.VALIDATE, TaskType.REPORT}
    
    # Minimum duration to justify distribution overhead
    DISTRIBUTION_THRESHOLD = 600  # 10 minutes
    
    # Cache remote results for 24 hours
    RESULT_CACHE_TTL = 86400
    
    def __init__(
        self,
        mesh_node: MeshNode,
        ledger_path: str = "/var/lib/aiworker/task_ledger.db"
    ):
        self.mesh_node = mesh_node
        self.node_id = mesh_node.config.node_id
        self.ledger = DistributedLedger(ledger_path, self.node_id)
        
        # Result cache
        self._result_cache: Dict[str, Tuple[Dict, float]] = {}
        
        # Active task tracking
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._task_locks: Dict[str, asyncio.Lock] = {}
        
        # Bidding state
        self._bidding_tasks: Dict[str, List[TaskBid]] = {}
        self._bid_event = asyncio.Event()
        
        # Sharding state
        self._shard_allocations: Dict[str, ShardAllocation] = {}
        
        # Callbacks
        self._task_handlers: Dict[TaskType, Callable] = {}
        self._completion_callbacks: List[Callable] = []
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False
        
        # Register mesh handlers
        self._register_handlers()
        
        logger.info("TaskOrchestrator initialized")
    
    def _register_handlers(self):
        """Register message handlers with mesh node."""
        self.mesh_node.register_handler(MessageType.TASK_OFFER, self._handle_task_offer)
        self.mesh_node.register_handler(MessageType.TASK_ACCEPT, self._handle_task_accept)
        self.mesh_node.register_handler(MessageType.TASK_COMPLETE, self._handle_task_complete)
        self.mesh_node.register_handler(MessageType.SYNC_REQUEST, self._handle_sync_request)
        self.mesh_node.register_handler(MessageType.SYNC_RESPONSE, self._handle_sync_response)
    
    async def start(self):
        """Start the orchestrator."""
        self._running = True
        
        # Start background tasks
        self._tasks.append(asyncio.create_task(self._timeout_monitor()))
        self._tasks.append(asyncio.create_task(self._cache_cleanup()))
        self._tasks.append(asyncio.create_task(self._ledger_sync()))
        
        logger.info("TaskOrchestrator started")
    
    async def stop(self):
        """Stop the orchestrator."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        # Cancel active tasks
        for task in self._active_tasks.values():
            task.cancel()
        
        logger.info("TaskOrchestrator stopped")
    
    async def distribute(self, task: Task) -> Optional[Dict[str, Any]]:
        """
        Distribute a task to the mesh or execute locally.
        
        Returns result if executed locally, None if distributed.
        """
        # Check if task should be local-only
        if task.task_type in self.LOCAL_ONLY_TASKS:
            logger.debug(f"Task {task.task_id} is local-only, executing locally")
            return await self._execute_local(task)
        
        # Check if task is too small to distribute
        if task.estimated_duration < self.DISTRIBUTION_THRESHOLD:
            logger.debug(f"Task {task.task_id} too small to distribute")
            return await self._execute_local(task)
        
        # Check cache for duplicate work
        cache_key = self._get_cache_key(task)
        if cache_key in self._result_cache:
            result, cached_at = self._result_cache[cache_key]
            if time.time() - cached_at < self.RESULT_CACHE_TTL:
                logger.debug(f"Returning cached result for {task.task_id}")
                return result
        
        # Check if similar task already in mesh
        existing = self._find_similar_task(task)
        if existing:
            logger.info(f"Similar task {existing.task_id} exists, waiting for completion")
            return await self._wait_for_task(existing.task_id)
        
        # Add to ledger
        task.created_by = self.node_id
        self.ledger.create_task(task)
        
        # If we're coordinator, handle assignment
        if self.mesh_node.is_coordinator():
            await self._coordinate_assignment(task)
        else:
            # Announce to mesh and wait for assignment
            await self._announce_task(task)
        
        return None
    
    async def _execute_local(self, task: Task) -> Dict[str, Any]:
        """Execute task locally."""
        handler = self._task_handlers.get(task.task_type)
        if not handler:
            raise ValueError(f"No handler for task type {task.task_type}")
        
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        
        try:
            result = await handler(task.payload)
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            
            # Cache result
            cache_key = self._get_cache_key(task)
            self._result_cache[cache_key] = (result, time.time())
            
            return result
            
        except Exception as e:
            task.error = str(e)
            task.status = TaskStatus.FAILED
            raise
    
    async def _announce_task(self, task: Task):
        """Announce task to mesh for bidding."""
        message = MeshMessage(
            msg_type=MessageType.TASK_OFFER,
            sender_id=self.node_id,
            payload={
                "task": task.to_dict(),
                "bidding_deadline": time.time() + 30  # 30 second bidding window
            }
        )
        
        await self.mesh_node.broadcast(message)
        logger.info(f"Announced task {task.task_id} to mesh")
    
    async def _coordinate_assignment(self, task: Task):
        """As coordinator, assign task to best bidder."""
        # Wait for bids
        await asyncio.sleep(5)  # Short bidding window
        
        bids = self.ledger.get_bids(task.task_id)
        
        if not bids:
            logger.warning(f"No bids for task {task.task_id}, executing locally")
            await self._execute_local(task)
            return
        
        # Select best bid (lowest score)
        best_bid = min(bids)
        
        # Assign task
        self.ledger.update_task_status(
            task.task_id,
            TaskStatus.ASSIGNED,
            assigned_to=best_bid.node_id
        )
        
        # Announce assignment
        message = MeshMessage(
            msg_type=MessageType.TASK_ACCEPT,
            sender_id=self.node_id,
            payload={
                "task_id": task.task_id,
                "assigned_to": best_bid.node_id,
                "coordinator": self.node_id
            }
        )
        
        await self.mesh_node.broadcast(message)
        logger.info(f"Assigned task {task.task_id} to {best_bid.node_id}")
    
    async def _handle_task_offer(self, message: MeshMessage, protocol):
        """Handle task offer from another node."""
        task_data = message.payload.get("task", {})
        task = Task.from_dict(task_data)
        
        # Check if we should bid
        if not self._should_bid(task):
            return
        
        # Calculate bid score
        bid_score = self._calculate_bid_score(task)
        
        # Submit bid
        bid = TaskBid(
            task_id=task.task_id,
            node_id=self.node_id,
            bid_score=bid_score,
            capabilities=self.mesh_node.capabilities.to_dict(),
            estimated_completion=time.time() + task.estimated_duration
        )
        
        self.ledger.add_bid(bid)
        
        # Send bid to coordinator
        bid_message = MeshMessage(
            msg_type=MessageType.TASK_OFFER,
            sender_id=self.node_id,
            payload={
                "bid": {
                    "task_id": bid.task_id,
                    "node_id": bid.node_id,
                    "bid_score": bid.bid_score,
                    "capabilities": bid.capabilities,
                    "estimated_completion": bid.estimated_completion
                }
            }
        )
        
        coordinator = self.mesh_node.get_coordinator()
        if coordinator:
            await self.mesh_node.send_to(coordinator, bid_message)
        
        logger.debug(f"Submitted bid for task {task.task_id}: score={bid_score}")
    
    def _should_bid(self, task: Task) -> bool:
        """Determine if this node should bid on a task."""
        # Check capability match
        if task.task_type == TaskType.RECON:
            # RECON tasks need memory for wordlists
            if self.mesh_node.capabilities.ram_gb < 16:
                return False
        
        elif task.task_type == TaskType.ANALYZE:
            # ANALYZE tasks benefit from GPU
            if not self.mesh_node.capabilities.has_gpu:
                return False
        
        # Check load
        if self.mesh_node.capabilities.current_load > 0.8:
            return False
        
        # Check if already have too many tasks
        if self.mesh_node.capabilities.active_tasks >= 3:
            return False
        
        return True
    
    def _calculate_bid_score(self, task: Task) -> float:
        """Calculate bid score (lower is better)."""
        score = 0.0
        caps = self.mesh_node.capabilities
        
        # Load factor (heavily weighted)
        score += caps.current_load * 100
        
        # Queue depth
        score += caps.queue_depth * 10
        
        # Capability match bonus
        if task.task_type == TaskType.RECON and caps.ram_gb >= 32:
            score -= 20
        
        if task.task_type == TaskType.ANALYZE and caps.has_gpu:
            score -= 30
        
        # Success rate bonus
        score -= caps.success_rate * 10
        
        # Random factor to prevent ties
        score += hashlib.sha256(
            f"{self.node_id}:{task.task_id}".encode()
        ).hexdigest()[:4]
        
        return score
    
    async def _handle_task_accept(self, message: MeshMessage, protocol):
        """Handle task assignment."""
        task_id = message.payload.get("task_id")
        assigned_to = message.payload.get("assigned_to")
        
        if assigned_to == self.node_id:
            # We won the bid, execute task
            task = self.ledger.get_task(task_id)
            if task:
                logger.info(f"Won bid for task {task_id}, executing")
                asyncio.create_task(self._execute_distributed_task(task))
    
    async def _execute_distributed_task(self, task: Task):
        """Execute a task that was assigned to us."""
        self.ledger.update_task_status(task.task_id, TaskStatus.RUNNING)
        
        try:
            result = await self._execute_local(task)
            
            # Announce completion
            message = MeshMessage(
                msg_type=MessageType.TASK_COMPLETE,
                sender_id=self.node_id,
                payload={
                    "task_id": task.task_id,
                    "result": result,
                    "completed_by": self.node_id
                }
            )
            
            await self.mesh_node.broadcast(message)
            
        except Exception as e:
            logger.error(f"Task {task.task_id} failed: {e}")
            
            # Announce failure
            message = MeshMessage(
                msg_type=MessageType.TASK_COMPLETE,
                sender_id=self.node_id,
                payload={
                    "task_id": task.task_id,
                    "error": str(e),
                    "failed_by": self.node_id
                }
            )
            
            await self.mesh_node.broadcast(message)
    
    async def _handle_task_complete(self, message: MeshMessage, protocol):
        """Handle task completion."""
        task_id = message.payload.get("task_id")
        result = message.payload.get("result")
        error = message.payload.get("error")
        
        if result:
            self.ledger.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                result=result
            )
            
            # Cache result
            task = self.ledger.get_task(task_id)
            if task:
                cache_key = self._get_cache_key(task)
                self._result_cache[cache_key] = (result, time.time())
            
            logger.info(f"Task {task_id} completed by {message.sender_id}")
            
        elif error:
            self.ledger.update_task_status(
                task_id,
                TaskStatus.FAILED,
                error=error
            )
            
            logger.warning(f"Task {task_id} failed: {error}")
        
        # Notify callbacks
        for callback in self._completion_callbacks:
            try:
                await callback(task_id, result, error)
            except Exception as e:
                logger.error(f"Completion callback error: {e}")
    
    def _get_cache_key(self, task: Task) -> str:
        """Generate cache key for a task."""
        key_data = f"{task.task_type.value}:{json.dumps(task.payload, sort_keys=True)}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:32]
    
    def _find_similar_task(self, task: Task) -> Optional[Task]:
        """Find a similar task already in the system."""
        cache_key = self._get_cache_key(task)
        
        # Check pending/assigned/running tasks
        for status in [TaskStatus.PENDING, TaskStatus.BIDDING, 
                       TaskStatus.ASSIGNED, TaskStatus.RUNNING]:
            tasks = self.ledger.get_tasks_by_status(status)
            for t in tasks:
                if self._get_cache_key(t) == cache_key:
                    return t
        
        return None
    
    async def _wait_for_task(self, task_id: str) -> Dict[str, Any]:
        """Wait for a task to complete."""
        while True:
            task = self.ledger.get_task(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            
            if task.status == TaskStatus.COMPLETED:
                return task.result
            
            if task.status == TaskStatus.FAILED:
                raise Exception(f"Task {task_id} failed: {task.error}")
            
            await asyncio.sleep(1)
    
    async def _timeout_monitor(self):
        """Monitor for timed-out tasks and reassign."""
        while self._running:
            try:
                await asyncio.sleep(60)
                
                running_tasks = self.ledger.get_tasks_by_status(TaskStatus.RUNNING)
                
                for task in running_tasks:
                    if task.started_at:
                        elapsed = time.time() - task.started_at
                        
                        # Timeout if exceeded 2x estimated duration
                        if elapsed > task.estimated_duration * 2:
                            logger.warning(f"Task {task.task_id} timed out")
                            
                            # Mark as failed
                            self.ledger.update_task_status(
                                task.task_id,
                                TaskStatus.FAILED,
                                error="Timeout"
                            )
                            
                            # If coordinator, reassign
                            if self.mesh_node.is_coordinator():
                                # Get next best bid
                                bids = self.ledger.get_bids(task.task_id)
                                other_bids = [b for b in bids if b.node_id != task.assigned_to]
                                
                                if other_bids:
                                    next_bid = min(other_bids)
                                    self.ledger.update_task_status(
                                        task.task_id,
                                        TaskStatus.ASSIGNED,
                                        assigned_to=next_bid.node_id
                                    )
                                    
                                    # Announce reassignment
                                    message = MeshMessage(
                                        msg_type=MessageType.TASK_ACCEPT,
                                        sender_id=self.node_id,
                                        payload={
                                            "task_id": task.task_id,
                                            "assigned_to": next_bid.node_id,
                                            "reassigned": True
                                        }
                                    )
                                    await self.mesh_node.broadcast(message)
                                    
            except Exception as e:
                logger.error(f"Timeout monitor error: {e}")
    
    async def _cache_cleanup(self):
        """Clean expired cache entries."""
        while self._running:
            try:
                await asyncio.sleep(3600)  # Every hour
                
                now = time.time()
                expired = [
                    key for key, (_, cached_at) in self._result_cache.items()
                    if now - cached_at > self.RESULT_CACHE_TTL
                ]
                
                for key in expired:
                    del self._result_cache[key]
                
                if expired:
                    logger.debug(f"Cleaned {len(expired)} expired cache entries")
                    
            except Exception as e:
                logger.error(f"Cache cleanup error: {e}")
    
    async def _ledger_sync(self):
        """Periodically sync ledger with peers."""
        while self._running:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                
                # Request sync from all peers
                message = MeshMessage(
                    msg_type=MessageType.SYNC_REQUEST,
                    sender_id=self.node_id,
                    payload={"since": time.time() - 3600}  # Last hour
                )
                
                await self.mesh_node.broadcast(message)
                
            except Exception as e:
                logger.error(f"Ledger sync error: {e}")
    
    async def _handle_sync_request(self, message: MeshMessage, protocol):
        """Handle sync request from peer."""
        since = message.payload.get("since", 0)
        
        # Get delta
        delta = self.ledger.get_delta_since(since)
        
        # Send response
        response = MeshMessage(
            msg_type=MessageType.SYNC_RESPONSE,
            sender_id=self.node_id,
            payload=delta
        )
        
        await self.mesh_node.send_to(message.sender_id, response)
    
    async def _handle_sync_response(self, message: MeshMessage, protocol):
        """Handle sync response from peer."""
        delta = message.payload
        
        # Apply delta
        applied = self.ledger.apply_delta(delta)
        
        logger.debug(f"Applied {applied} changes from sync with {message.sender_id}")
    
    def register_task_handler(self, task_type: TaskType, handler: Callable):
        """Register a handler for a task type."""
        self._task_handlers[task_type] = handler
    
    def on_completion(self, callback: Callable):
        """Register a callback for task completion."""
        self._completion_callbacks.append(callback)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        return {
            "pending_tasks": len(self.ledger.get_tasks_by_status(TaskStatus.PENDING)),
            "running_tasks": len(self.ledger.get_tasks_by_status(TaskStatus.RUNNING)),
            "completed_tasks": len(self.ledger.get_tasks_by_status(TaskStatus.COMPLETED)),
            "failed_tasks": len(self.ledger.get_tasks_by_status(TaskStatus.FAILED)),
            "cached_results": len(self._result_cache),
            "is_coordinator": self.mesh_node.is_coordinator(),
        }


# Convenience functions
async def create_orchestrator(mesh_node: MeshNode) -> TaskOrchestrator:
    """Create and start a task orchestrator."""
    orchestrator = TaskOrchestrator(mesh_node)
    await orchestrator.start()
    return orchestrator
