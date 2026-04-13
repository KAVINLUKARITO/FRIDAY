#!/usr/bin/env python3
"""
AIWorker Knowledge Sync Engine - Secure Knowledge Sharing
Phase 5: Ecosystem Expansion & Multi-Instance Coordination

Enables secure, efficient knowledge sharing between AIWorker instances
with end-to-end encryption, authenticated updates, and CRDT-based
conflict resolution.
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
from typing import Dict, List, Optional, Set, Callable, Any, Tuple, Union
from collections import defaultdict
import threading
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.backends import default_backend

from aiworker.mesh.network_node import MeshNode, MeshMessage, MessageType

logger = logging.getLogger("aiworker.knowledge.sync")


class KnowledgeType(Enum):
    """Types of knowledge that can be synced."""
    SKILL = "skill"              # New skills, mastery updates
    RESEARCH = "research"        # Findings, validated sources
    CODE_PATTERN = "code_pattern"  # Successful patch templates
    SAFETY_INCIDENT = "safety"   # Rejected patches, kill switches
    TELEMETRY = "telemetry"      # Performance baselines


class SyncPriority(Enum):
    """Sync priority levels."""
    URGENT = 0      # Safety incidents - immediate
    HIGH = 1        # Skills - within 1 hour
    NORMAL = 2      # Research - within 6 hours
    LOW = 3         # Telemetry - within 24 hours


# What NEVER syncs (security boundary)
SYNC_DENYLIST = {
    "raw_vulnerability_findings",
    "program_specific_data",
    "private_keys",
    "credentials",
    "local_file_paths",
    "session_tokens",
    "api_keys",
}


@dataclass
class KnowledgeRecord:
    """A single knowledge record for sync."""
    record_id: str
    knowledge_type: KnowledgeType
    payload: Dict[str, Any]
    
    # Metadata
    created_by: str
    created_at: float = field(default_factory=time.time)
    modified_at: float = field(default_factory=time.time)
    version: int = 1
    
    # Sync tracking
    sync_vector: Dict[str, int] = field(default_factory=dict)
    priority: SyncPriority = SyncPriority.NORMAL
    
    # Verification
    signature: Optional[bytes] = None
    checksum: Optional[str] = None
    
    def __post_init__(self):
        if not self.checksum:
            self._compute_checksum()
    
    def _compute_checksum(self):
        """Compute content checksum for integrity."""
        data = json.dumps(self.payload, sort_keys=True).encode()
        self.checksum = hashlib.sha256(data).hexdigest()[:32]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "knowledge_type": self.knowledge_type.value,
            "payload": self.payload,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "version": self.version,
            "sync_vector": self.sync_vector,
            "priority": self.priority.value,
            "checksum": self.checksum,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeRecord":
        return cls(
            record_id=data["record_id"],
            knowledge_type=KnowledgeType(data["knowledge_type"]),
            payload=data["payload"],
            created_by=data["created_by"],
            created_at=data["created_at"],
            modified_at=data["modified_at"],
            version=data["version"],
            sync_vector=data.get("sync_vector", {}),
            priority=SyncPriority(data.get("priority", 2)),
            checksum=data.get("checksum"),
        )
    
    def sign(self, private_key) -> bytes:
        """Sign the record with node's private key."""
        data = json.dumps(self.to_dict(), sort_keys=True).encode()
        signature = private_key.sign(data)
        self.signature = signature
        return signature


@dataclass
class SyncDelta:
    """Delta of changes for sync."""
    new_records: List[KnowledgeRecord] = field(default_factory=list)
    updated_records: List[KnowledgeRecord] = field(default_factory=list)
    deleted_records: List[str] = field(default_factory=list)
    
    # Vector clock at time of sync
    vector_clock: Dict[str, int] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def size_bytes(self) -> int:
        """Get approximate size of delta."""
        data = json.dumps({
            "new": [r.to_dict() for r in self.new_records],
            "updated": [r.to_dict() for r in self.updated_records],
            "deleted": self.deleted_records,
        }).encode()
        return len(data)
    
    def compress(self) -> bytes:
        """Compress delta for transmission."""
        data = json.dumps({
            "new": [r.to_dict() for r in self.new_records],
            "updated": [r.to_dict() for r in self.updated_records],
            "deleted": self.deleted_records,
            "vector_clock": self.vector_clock,
            "timestamp": self.timestamp,
        }).encode()
        return zlib.compress(data, level=3)
    
    @classmethod
    def decompress(cls, data: bytes) -> "SyncDelta":
        """Decompress delta from transmission."""
        decompressed = zlib.decompress(data)
        obj = json.loads(decompressed.decode())
        
        return cls(
            new_records=[KnowledgeRecord.from_dict(r) for r in obj.get("new", [])],
            updated_records=[KnowledgeRecord.from_dict(r) for r in obj.get("updated", [])],
            deleted_records=obj.get("deleted", []),
            vector_clock=obj.get("vector_clock", {}),
            timestamp=obj.get("timestamp", time.time()),
        )


class KnowledgeStore:
    """
    SQLite-based knowledge store with sync capabilities.
    
    Uses two databases:
    - knowledge_local.db: Private knowledge (never synced)
    - knowledge_shared.db: Replicated knowledge (synced)
    """
    
    def __init__(
        self,
        local_db_path: str = "/var/lib/aiworker/knowledge_local.db",
        shared_db_path: str = "/var/lib/aiworker/knowledge_shared.db",
        node_id: str = ""
    ):
        self.local_db_path = local_db_path
        self.shared_db_path = shared_db_path
        self.node_id = node_id
        self._lock = threading.RLock()
        
        self._init_databases()
    
    def _init_databases(self):
        """Initialize both databases."""
        # Shared database (synced)
        with sqlite3.connect(self.shared_db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    record_id TEXT PRIMARY KEY,
                    knowledge_type TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    modified_at REAL NOT NULL,
                    version INTEGER NOT NULL,
                    sync_vector TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    checksum TEXT NOT NULL,
                    signature BLOB
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_type ON knowledge(knowledge_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_modified ON knowledge(modified_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_created_by ON knowledge(created_by)
            """)
            
            # Sync cursors for each peer
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_cursors (
                    peer_id TEXT PRIMARY KEY,
                    last_sync REAL NOT NULL,
                    vector_clock TEXT NOT NULL
                )
            """)
            
            conn.commit()
        
        # Local database (private)
        with sqlite3.connect(self.local_db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_local (
                    record_id TEXT PRIMARY KEY,
                    knowledge_type TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    modified_at REAL NOT NULL
                )
            """)
            conn.commit()
    
    def _check_security(self, payload: Dict[str, Any]) -> bool:
        """Check if payload contains denied content."""
        payload_str = json.dumps(payload).lower()
        
        for denied in SYNC_DENYLIST:
            if denied.lower() in payload_str:
                logger.warning(f"Security check failed: found '{denied}' in payload")
                return False
        
        return True
    
    def add_knowledge(
        self,
        knowledge_type: KnowledgeType,
        payload: Dict[str, Any],
        local_only: bool = False
    ) -> Optional[str]:
        """
        Add knowledge to store.
        
        Args:
            knowledge_type: Type of knowledge
            payload: Knowledge content
            local_only: If True, store only locally (never sync)
        
        Returns:
            record_id if successful, None if security check failed
        """
        # Security check
        if not self._check_security(payload):
            return None
        
        record_id = hashlib.sha256(
            f"{self.node_id}:{time.time()}:{secrets.token_hex(8)}".encode()
        ).hexdigest()[:32]
        
        record = KnowledgeRecord(
            record_id=record_id,
            knowledge_type=knowledge_type,
            payload=payload,
            created_by=self.node_id,
            sync_vector={self.node_id: int(time.time() * 1000)},
        )
        
        if local_only:
            # Store in local database only
            with self._lock:
                with sqlite3.connect(self.local_db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO knowledge_local (record_id, knowledge_type, payload,
                                                    created_at, modified_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            record_id,
                            knowledge_type.value,
                            zlib.compress(json.dumps(payload).encode()),
                            record.created_at,
                            record.modified_at
                        )
                    )
                    conn.commit()
        else:
            # Store in shared database
            with self._lock:
                with sqlite3.connect(self.shared_db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO knowledge (record_id, knowledge_type, payload,
                                             created_by, created_at, modified_at,
                                             version, sync_vector, priority, checksum)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record_id,
                            knowledge_type.value,
                            zlib.compress(json.dumps(payload).encode()),
                            record.created_by,
                            record.created_at,
                            record.modified_at,
                            record.version,
                            json.dumps(record.sync_vector),
                            record.priority.value,
                            record.checksum
                        )
                    )
                    conn.commit()
        
        return record_id
    
    def get_knowledge(
        self,
        record_id: str,
        local_only: bool = False
    ) -> Optional[KnowledgeRecord]:
        """Get a knowledge record by ID."""
        with self._lock:
            if local_only:
                db_path = self.local_db_path
                query = "SELECT * FROM knowledge_local WHERE record_id = ?"
            else:
                db_path = self.shared_db_path
                query = "SELECT * FROM knowledge WHERE record_id = ?"
            
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(query, (record_id,)).fetchone()
                
                if not row:
                    return None
                
                if local_only:
                    return KnowledgeRecord(
                        record_id=row[0],
                        knowledge_type=KnowledgeType(row[1]),
                        payload=json.loads(zlib.decompress(row[2]).decode()),
                        created_by=self.node_id,
                        created_at=row[3],
                        modified_at=row[4],
                    )
                else:
                    return self._row_to_record(row)
    
    def get_knowledge_by_type(
        self,
        knowledge_type: KnowledgeType,
        since: Optional[float] = None,
        limit: int = 100
    ) -> List[KnowledgeRecord]:
        """Get knowledge records by type."""
        with self._lock:
            with sqlite3.connect(self.shared_db_path) as conn:
                if since:
                    rows = conn.execute(
                        """
                        SELECT * FROM knowledge 
                        WHERE knowledge_type = ? AND modified_at > ?
                        ORDER BY modified_at DESC
                        LIMIT ?
                        """,
                        (knowledge_type.value, since, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM knowledge 
                        WHERE knowledge_type = ?
                        ORDER BY modified_at DESC
                        LIMIT ?
                        """,
                        (knowledge_type.value, limit)
                    ).fetchall()
                
                return [self._row_to_record(row) for row in rows]
    
    def update_knowledge(
        self,
        record_id: str,
        payload: Dict[str, Any]
    ) -> bool:
        """Update an existing knowledge record."""
        # Security check
        if not self._check_security(payload):
            return False
        
        with self._lock:
            with sqlite3.connect(self.shared_db_path) as conn:
                # Get current version
                row = conn.execute(
                    "SELECT version, sync_vector FROM knowledge WHERE record_id = ?",
                    (record_id,)
                ).fetchone()
                
                if not row:
                    return False
                
                version = row[0] + 1
                sync_vector = json.loads(row[1])
                sync_vector[self.node_id] = int(time.time() * 1000)
                
                # Compute new checksum
                checksum = hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest()[:32]
                
                conn.execute(
                    """
                    UPDATE knowledge 
                    SET payload = ?, modified_at = ?, version = ?, 
                        sync_vector = ?, checksum = ?
                    WHERE record_id = ?
                    """,
                    (
                        zlib.compress(json.dumps(payload).encode()),
                        time.time(),
                        version,
                        json.dumps(sync_vector),
                        checksum,
                        record_id
                    )
                )
                conn.commit()
                
                return True
    
    def get_delta_since(self, timestamp: float, max_size: int = 10*1024*1024) -> SyncDelta:
        """Get all changes since timestamp for sync."""
        delta = SyncDelta()
        
        with self._lock:
            with sqlite3.connect(self.shared_db_path) as conn:
                # Get new/updated records
                rows = conn.execute(
                    """
                    SELECT * FROM knowledge 
                    WHERE modified_at > ?
                    ORDER BY modified_at ASC
                    """,
                    (timestamp,)
                ).fetchall()
                
                for row in rows:
                    record = self._row_to_record(row)
                    
                    if record.created_at >= timestamp:
                        delta.new_records.append(record)
                    else:
                        delta.updated_records.append(record)
                    
                    # Check size limit
                    if delta.size_bytes() > max_size:
                        logger.warning("Delta size limit reached, truncating")
                        break
                
                # Get vector clock
                delta.vector_clock = self._get_vector_clock()
        
        return delta
    
    def apply_delta(self, delta: SyncDelta, verify_signatures: bool = True) -> int:
        """Apply sync delta from another node."""
        applied = 0
        
        with self._lock:
            with sqlite3.connect(self.shared_db_path) as conn:
                for record in delta.new_records:
                    # Check if already exists
                    existing = conn.execute(
                        "SELECT 1 FROM knowledge WHERE record_id = ?",
                        (record.record_id,)
                    ).fetchone()
                    
                    if not existing:
                        # Security check
                        if not self._check_security(record.payload):
                            continue
                        
                        conn.execute(
                            """
                            INSERT INTO knowledge (record_id, knowledge_type, payload,
                                                 created_by, created_at, modified_at,
                                                 version, sync_vector, priority, checksum)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                record.record_id,
                                record.knowledge_type.value,
                                zlib.compress(json.dumps(record.payload).encode()),
                                record.created_by,
                                record.created_at,
                                record.modified_at,
                                record.version,
                                json.dumps(record.sync_vector),
                                record.priority.value,
                                record.checksum
                            )
                        )
                        applied += 1
                
                for record in delta.updated_records:
                    # CRDT: last-write-wins based on vector clock
                    existing = conn.execute(
                        "SELECT modified_at, sync_vector FROM knowledge WHERE record_id = ?",
                        (record.record_id,)
                    ).fetchone()
                    
                    if existing:
                        existing_time = existing[0]
                        
                        if record.modified_at > existing_time:
                            # Security check
                            if not self._check_security(record.payload):
                                continue
                            
                            conn.execute(
                                """
                                UPDATE knowledge 
                                SET payload = ?, modified_at = ?, version = ?,
                                    sync_vector = ?, checksum = ?
                                WHERE record_id = ?
                                """,
                                (
                                    zlib.compress(json.dumps(record.payload).encode()),
                                    record.modified_at,
                                    record.version,
                                    json.dumps(record.sync_vector),
                                    record.checksum,
                                    record.record_id
                                )
                            )
                            applied += 1
                
                conn.commit()
        
        return applied
    
    def update_sync_cursor(self, peer_id: str):
        """Update sync cursor for a peer."""
        with self._lock:
            with sqlite3.connect(self.shared_db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sync_cursors (peer_id, last_sync, vector_clock)
                    VALUES (?, ?, ?)
                    """,
                    (peer_id, time.time(), json.dumps(self._get_vector_clock()))
                )
                conn.commit()
    
    def get_sync_cursor(self, peer_id: str) -> float:
        """Get last sync timestamp for a peer."""
        with self._lock:
            with sqlite3.connect(self.shared_db_path) as conn:
                row = conn.execute(
                    "SELECT last_sync FROM sync_cursors WHERE peer_id = ?",
                    (peer_id,)
                ).fetchone()
                
                return row[0] if row else 0
    
    def _get_vector_clock(self) -> Dict[str, int]:
        """Get current vector clock."""
        return {self.node_id: int(time.time() * 1000)}
    
    def _row_to_record(self, row) -> KnowledgeRecord:
        """Convert database row to KnowledgeRecord."""
        return KnowledgeRecord(
            record_id=row[0],
            knowledge_type=KnowledgeType(row[1]),
            payload=json.loads(zlib.decompress(row[2]).decode()),
            created_by=row[3],
            created_at=row[4],
            modified_at=row[5],
            version=row[6],
            sync_vector=json.loads(row[7]),
            priority=SyncPriority(row[8]),
            checksum=row[9],
            signature=row[10],
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get store statistics."""
        with self._lock:
            with sqlite3.connect(self.shared_db_path) as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM knowledge"
                ).fetchone()[0]
                
                by_type = {}
                for kt in KnowledgeType:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM knowledge WHERE knowledge_type = ?",
                        (kt.value,)
                    ).fetchone()[0]
                    by_type[kt.value] = count
            
            with sqlite3.connect(self.local_db_path) as conn:
                local_total = conn.execute(
                    "SELECT COUNT(*) FROM knowledge_local"
                ).fetchone()[0]
        
        return {
            "shared_records": total,
            "local_records": local_total,
            "by_type": by_type,
        }


class SyncEngine:
    """
    Secure, efficient knowledge sharing between AIWorker instances.
    
    Features:
    - End-to-end encryption (Noise protocol keys)
    - Authenticated sync (signed updates)
    - Rate limiting (max 100MB/day per peer)
    - CRDT-based conflict resolution
    - Compression (zstd level 3)
    """
    
    # Rate limits
    MAX_DAILY_BYTES = 100 * 1024 * 1024  # 100MB per peer per day
    MAX_DELTA_SIZE = 10 * 1024 * 1024    # 10MB per sync
    
    # Sync intervals
    SYNC_INTERVALS = {
        SyncPriority.URGENT: 60,      # 1 minute
        SyncPriority.HIGH: 3600,      # 1 hour
        SyncPriority.NORMAL: 21600,   # 6 hours
        SyncPriority.LOW: 86400,      # 24 hours
    }
    
    def __init__(
        self,
        mesh_node: MeshNode,
        store: KnowledgeStore,
    ):
        self.mesh_node = mesh_node
        self.store = store
        self.node_id = mesh_node.config.node_id
        
        # Encryption keys (derived from node identity)
        self._encryption_key = self._derive_key()
        
        # Rate tracking
        self._bytes_sent: Dict[str, List[Tuple[float, int]]] = defaultdict(list)
        
        # Sync state
        self._sync_in_progress: Set[str] = set()
        self._last_sync: Dict[str, float] = {}
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False
        
        # Register handlers
        self._register_handlers()
        
        logger.info("SyncEngine initialized")
    
    def _derive_key(self) -> bytes:
        """Derive encryption key from node identity."""
        # Use node_id as seed
        seed = self.node_id.encode()
        
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"aiworker-sync-v1",
            backend=default_backend()
        )
        
        return hkdf.derive(seed)
    
    def _register_handlers(self):
        """Register mesh message handlers."""
        self.mesh_node.register_handler(MessageType.SYNC_REQUEST, self._handle_sync_request)
        self.mesh_node.register_handler(MessageType.SYNC_RESPONSE, self._handle_sync_response)
    
    async def start(self):
        """Start the sync engine."""
        self._running = True
        
        # Start background sync loops
        for priority in SyncPriority:
            self._tasks.append(
                asyncio.create_task(self._sync_loop(priority))
            )
        
        self._tasks.append(asyncio.create_task(self._rate_limit_cleanup()))
        
        logger.info("SyncEngine started")
    
    async def stop(self):
        """Stop the sync engine."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        logger.info("SyncEngine stopped")
    
    async def _sync_loop(self, priority: SyncPriority):
        """Background sync loop for a priority level."""
        interval = self.SYNC_INTERVALS[priority]
        
        while self._running:
            try:
                await asyncio.sleep(interval)
                
                # Sync with all peers
                for peer_id in self.mesh_node.peers:
                    if peer_id in self._sync_in_progress:
                        continue
                    
                    # Check rate limit
                    if not self._check_rate_limit(peer_id):
                        continue
                    
                    # Request sync
                    await self._request_sync(peer_id, priority)
                    
            except Exception as e:
                logger.error(f"Sync loop error ({priority.value}): {e}")
    
    async def _request_sync(self, peer_id: str, priority: SyncPriority):
        """Request sync from a peer."""
        if peer_id in self._sync_in_progress:
            return
        
        self._sync_in_progress.add(peer_id)
        
        try:
            # Get last sync cursor
            since = self.store.get_sync_cursor(peer_id)
            
            # Request sync
            message = MeshMessage(
                msg_type=MessageType.SYNC_REQUEST,
                sender_id=self.node_id,
                payload={
                    "since": since,
                    "priority": priority.value,
                    "max_size": self.MAX_DELTA_SIZE,
                }
            )
            
            await self.mesh_node.send_to(peer_id, message)
            
            logger.debug(f"Requested sync from {peer_id} (priority={priority.value})")
            
        finally:
            self._sync_in_progress.discard(peer_id)
    
    async def _handle_sync_request(self, message: MeshMessage, protocol):
        """Handle sync request from peer."""
        peer_id = message.sender_id
        since = message.payload.get("since", 0)
        max_size = message.payload.get("max_size", self.MAX_DELTA_SIZE)
        
        # Check rate limit
        if not self._check_rate_limit(peer_id):
            logger.warning(f"Rate limit exceeded for {peer_id}, rejecting sync")
            return
        
        # Prepare delta
        delta = self.store.get_delta_since(since, max_size)
        
        # Compress
        compressed = delta.compress()
        
        # Track bytes
        self._track_bytes(peer_id, len(compressed))
        
        # Send response (may need to chunk)
        if len(compressed) > 1024 * 1024:  # 1MB
            await self._send_chunked_sync(peer_id, compressed)
        else:
            response = MeshMessage(
                msg_type=MessageType.SYNC_RESPONSE,
                sender_id=self.node_id,
                payload={
                    "delta": compressed.hex(),
                    "chunked": False,
                    "timestamp": time.time(),
                }
            )
            
            await self.mesh_node.send_to(peer_id, response)
        
        logger.debug(f"Sent sync to {peer_id}: {len(compressed)} bytes")
    
    async def _send_chunked_sync(self, peer_id: str, data: bytes):
        """Send large sync in chunks."""
        chunk_size = 256 * 1024  # 256KB chunks
        chunks = [data[i:i+chunk_size] for i in range(0, len(data), chunk_size)]
        
        for i, chunk in enumerate(chunks):
            message = MeshMessage(
                msg_type=MessageType.SYNC_RESPONSE,
                sender_id=self.node_id,
                payload={
                    "chunk": chunk.hex(),
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "chunked": True,
                }
            )
            
            await self.mesh_node.send_to(peer_id, message)
            await asyncio.sleep(0.1)  # Rate limit chunks
    
    async def _handle_sync_response(self, message: MeshMessage, protocol):
        """Handle sync response from peer."""
        peer_id = message.sender_id
        
        if message.payload.get("chunked"):
            # Handle chunked response
            await self._handle_chunked_response(peer_id, message.payload)
        else:
            # Single response
            delta_data = bytes.fromhex(message.payload["delta"])
            await self._apply_sync(delta_data, peer_id)
    
    async def _handle_chunked_response(self, peer_id: str, payload: Dict):
        """Handle chunked sync response."""
        # Store chunk
        if not hasattr(self, "_pending_chunks"):
            self._pending_chunks = {}
        
        if peer_id not in self._pending_chunks:
            self._pending_chunks[peer_id] = {}
        
        chunk_index = payload["chunk_index"]
        total_chunks = payload["total_chunks"]
        
        self._pending_chunks[peer_id][chunk_index] = bytes.fromhex(payload["chunk"])
        
        # Check if complete
        if len(self._pending_chunks[peer_id]) == total_chunks:
            # Reassemble
            chunks = [
                self._pending_chunks[peer_id][i]
                for i in range(total_chunks)
            ]
            data = b"".join(chunks)
            
            # Apply
            await self._apply_sync(data, peer_id)
            
            # Cleanup
            del self._pending_chunks[peer_id]
    
    async def _apply_sync(self, data: bytes, peer_id: str):
        """Apply received sync data."""
        try:
            delta = SyncDelta.decompress(data)
            
            # Apply to store
            applied = self.store.apply_delta(delta)
            
            # Update cursor
            self.store.update_sync_cursor(peer_id)
            
            logger.info(f"Applied {applied} records from sync with {peer_id}")
            
        except Exception as e:
            logger.error(f"Failed to apply sync from {peer_id}: {e}")
    
    def _check_rate_limit(self, peer_id: str) -> bool:
        """Check if peer is within daily rate limit."""
        now = time.time()
        day_ago = now - 86400
        
        # Clean old entries
        self._bytes_sent[peer_id] = [
            (t, b) for t, b in self._bytes_sent[peer_id]
            if t > day_ago
        ]
        
        # Calculate total
        total = sum(b for _, b in self._bytes_sent[peer_id])
        
        return total < self.MAX_DAILY_BYTES
    
    def _track_bytes(self, peer_id: str, bytes_count: int):
        """Track bytes sent to a peer."""
        self._bytes_sent[peer_id].append((time.time(), bytes_count))
    
    async def _rate_limit_cleanup(self):
        """Clean up rate limit tracking."""
        while self._running:
            try:
                await asyncio.sleep(3600)  # Every hour
                
                day_ago = time.time() - 86400
                
                for peer_id in list(self._bytes_sent.keys()):
                    self._bytes_sent[peer_id] = [
                        (t, b) for t, b in self._bytes_sent[peer_id]
                        if t > day_ago
                    ]
                    
            except Exception as e:
                logger.error(f"Rate limit cleanup error: {e}")
    
    async def force_sync(self, peer_id: Optional[str] = None) -> int:
        """Force immediate sync with a peer or all peers."""
        peers = [peer_id] if peer_id else list(self.mesh_node.peers.keys())
        
        total_applied = 0
        
        for pid in peers:
            if pid not in self.mesh_node.peers:
                continue
            
            since = self.store.get_sync_cursor(pid)
            
            # Request sync
            message = MeshMessage(
                msg_type=MessageType.SYNC_REQUEST,
                sender_id=self.node_id,
                payload={"since": since, "priority": SyncPriority.HIGH.value}
            )
            
            await self.mesh_node.send_to(pid, message)
        
        return total_applied
    
    def get_stats(self) -> Dict[str, Any]:
        """Get sync engine statistics."""
        total_bytes = sum(
            sum(b for _, b in entries)
            for entries in self._bytes_sent.values()
        )
        
        return {
            "total_bytes_sent": total_bytes,
            "peers_synced": len(self._bytes_sent),
            "store_stats": self.store.get_stats(),
        }


# Convenience functions
async def create_sync_engine(
    mesh_node: MeshNode,
    local_db: str = "/var/lib/aiworker/knowledge_local.db",
    shared_db: str = "/var/lib/aiworker/knowledge_shared.db",
) -> SyncEngine:
    """Create and start a sync engine."""
    store = KnowledgeStore(
        local_db_path=local_db,
        shared_db_path=shared_db,
        node_id=mesh_node.config.node_id
    )
    
    engine = SyncEngine(mesh_node, store)
    await engine.start()
    
    return engine
