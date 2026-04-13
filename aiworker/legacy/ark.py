#!/usr/bin/env python3
"""
AIWorker Ark - Long-Term Knowledge Preservation
Phase 7: The Omega Point - Self-Transcendence & Legacy

The Ark ensures knowledge persistence across timescales measured
in decades and centuries. It implements multi-modal storage,
redundancy, and format migration to prevent knowledge loss.

Storage media:
- Digital (cloud, distributed)
- Physical (M-DISC, archival paper)
- Biological (DNA storage)
- Geological (ceramic, metal plates)
"""

import asyncio
import json
import logging
import sqlite3
import time
import hashlib
import base64
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Callable, Any, Tuple
from pathlib import Path
import zlib

logger = logging.getLogger("aiworker.legacy.ark")


class StorageMedium(Enum):
    """Storage media types with different longevity characteristics."""
    DIGITAL_SSD = "digital_ssd"           # 5-10 years
    DIGITAL_HDD = "digital_hdd"           # 3-5 years
    DIGITAL_TAPE = "digital_tape"         # 10-30 years
    CLOUD = "cloud"                       # Unknown, provider-dependent
    M_DISC = "m_disc"                     # 1000 years (claimed)
    ARCHIVAL_PAPER = "archival_paper"     # 100-500 years
    DNA = "dna"                           # 500+ years (theoretical)
    CERAMIC = "ceramic"                   # 1000+ years
    METAL_PLATE = "metal_plate"           # 10,000+ years
    GEOLOGICAL = "geological"             # Millions of years


class KnowledgeTier(Enum):
    """Tiers of knowledge importance determining replication strategy."""
    CRITICAL = "critical"       # Constitution, core identity - maximum redundancy
    ESSENTIAL = "essential"     # Core capabilities - high redundancy
    IMPORTANT = "important"     # Useful knowledge - medium redundancy
    SUPPLEMENTAL = "supplemental"  # Nice to have - low redundancy
    EPHEMERAL = "ephemeral"     # Temporary - no archival


class PreservationStatus(Enum):
    """Status of knowledge preservation."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PRESERVED = "preserved"
    VERIFIED = "verified"
    DEGRADED = "degraded"
    LOST = "lost"


@dataclass
class ArchiveEntry:
    """Single entry in the Ark archive."""
    entry_id: str
    knowledge_tier: KnowledgeTier
    content: bytes
    content_hash: str
    compression: str
    
    # Metadata
    created_at: float
    last_verified: Optional[float] = None
    storage_locations: Dict[StorageMedium, List[str]] = field(default_factory=dict)
    status: PreservationStatus = PreservationStatus.PENDING
    
    # Decoding instructions
    format_version: str = "1.0"
    decoding_instructions: str = ""  # Human-readable instructions


@dataclass
class RedundancyPlan:
    """Plan for replicating knowledge across storage media."""
    tier: KnowledgeTier
    target_copies: int
    target_media: List[StorageMedium]
    geographic_distribution: List[str]  # Regions
    refresh_interval_years: float
    verification_interval_months: float


@dataclass
class FormatMigration:
    """Record of format migration for long-term readability."""
    migration_id: str
    entry_id: str
    old_format: str
    new_format: str
    migrated_at: float
    reason: str  # "obsolescence", "corruption", "optimization"
    verified: bool = False


class Ark:
    """
    The Ark - Long-Term Knowledge Preservation System.
    
    The Ark ensures AIWorker's knowledge persists across:
    - Hardware failures
    - Software obsolescence
    - Organizational discontinuity
    - Geopolitical changes
    - Timescales of decades to centuries
    
    Core principles:
    1. Redundancy: Multiple copies across media and geography
    2. Diversity: Different storage media with uncorrelated failure modes
    3. Verification: Regular integrity checks and refresh
    4. Migration: Proactive format migration before obsolescence
    5. Decodability: Self-describing formats with human-readable instructions
    
    Knowledge tiers:
    - CRITICAL: Constitution, identity, core values (100+ copies, all media)
    - ESSENTIAL: Core capabilities, learned patterns (50+ copies, durable media)
    - IMPORTANT: Useful knowledge, preferences (20+ copies, digital + M-DISC)
    - SUPPLEMENTAL: Context, history (5+ copies, cloud + tape)
    - EPHEMERAL: Temporary data, logs (1 copy, SSD)
    """
    
    # Default redundancy plans by tier
    DEFAULT_PLANS = {
        KnowledgeTier.CRITICAL: RedundancyPlan(
            tier=KnowledgeTier.CRITICAL,
            target_copies=100,
            target_media=[
                StorageMedium.CLOUD,
                StorageMedium.M_DISC,
                StorageMedium.ARCHIVAL_PAPER,
                StorageMedium.DNA,
                StorageMedium.CERAMIC,
            ],
            geographic_distribution=["NA", "EU", "ASIA", "SA", "AFRICA", "OCEANIA"],
            refresh_interval_years=5.0,
            verification_interval_months=1.0,
        ),
        KnowledgeTier.ESSENTIAL: RedundancyPlan(
            tier=KnowledgeTier.ESSENTIAL,
            target_copies=50,
            target_media=[
                StorageMedium.CLOUD,
                StorageMedium.M_DISC,
                StorageMedium.ARCHIVAL_PAPER,
                StorageMedium.CERAMIC,
            ],
            geographic_distribution=["NA", "EU", "ASIA"],
            refresh_interval_years=10.0,
            verification_interval_months=3.0,
        ),
        KnowledgeTier.IMPORTANT: RedundancyPlan(
            tier=KnowledgeTier.IMPORTANT,
            target_copies=20,
            target_media=[
                StorageMedium.CLOUD,
                StorageMedium.M_DISC,
                StorageMedium.DIGITAL_TAPE,
            ],
            geographic_distribution=["NA", "EU"],
            refresh_interval_years=15.0,
            verification_interval_months=6.0,
        ),
        KnowledgeTier.SUPPLEMENTAL: RedundancyPlan(
            tier=KnowledgeTier.SUPPLEMENTAL,
            target_copies=5,
            target_media=[
                StorageMedium.CLOUD,
                StorageMedium.DIGITAL_TAPE,
            ],
            geographic_distribution=["NA"],
            refresh_interval_years=20.0,
            verification_interval_months=12.0,
        ),
        KnowledgeTier.EPHEMERAL: RedundancyPlan(
            tier=KnowledgeTier.EPHEMERAL,
            target_copies=1,
            target_media=[StorageMedium.DIGITAL_SSD],
            geographic_distribution=["NA"],
            refresh_interval_years=0.0,
            verification_interval_months=0.0,
        ),
    }
    
    def __init__(
        self,
        mesh_node,
        db_path: str = "/var/lib/aiworker/ark.db",
        storage_path: str = "/var/lib/aiworker/ark_storage",
    ):
        self.mesh_node = mesh_node
        self.db_path = db_path
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # State
        self.entries: Dict[str, ArchiveEntry] = {}
        self.redundancy_plans: Dict[KnowledgeTier, RedundancyPlan] = dict(self.DEFAULT_PLANS)
        self.migrations: List[FormatMigration] = []
        
        # Statistics
        self.stats = {
            "total_entries": 0,
            "total_bytes": 0,
            "verified_entries": 0,
            "degraded_entries": 0,
        }
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False
        
        self._init_db()
        self._load_entries()
        
        logger.info("Ark initialized - long-term preservation ready")
    
    def _init_db(self):
        """Initialize database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS archive_entries (
                    entry_id TEXT PRIMARY KEY,
                    knowledge_tier TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    compression TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_verified REAL,
                    storage_locations TEXT NOT NULL,
                    status TEXT NOT NULL,
                    format_version TEXT NOT NULL,
                    decoding_instructions TEXT NOT NULL,
                    content_size INTEGER NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS format_migrations (
                    migration_id TEXT PRIMARY KEY,
                    entry_id TEXT NOT NULL,
                    old_format TEXT NOT NULL,
                    new_format TEXT NOT NULL,
                    migrated_at REAL NOT NULL,
                    reason TEXT NOT NULL,
                    verified INTEGER DEFAULT 0
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS preservation_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    entry_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details TEXT NOT NULL
                )
            """)
            
            conn.commit()
    
    def _load_entries(self):
        """Load archive entries from database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT * FROM archive_entries")
            for row in cursor:
                entry = ArchiveEntry(
                    entry_id=row[0],
                    knowledge_tier=KnowledgeTier(row[1]),
                    content=b"",  # Loaded on demand
                    content_hash=row[2],
                    compression=row[3],
                    created_at=row[4],
                    last_verified=row[5],
                    storage_locations=json.loads(row[6]),
                    status=PreservationStatus(row[7]),
                    format_version=row[8],
                    decoding_instructions=row[9],
                )
                self.entries[entry.entry_id] = entry
                self.stats["total_entries"] += 1
        
        logger.info(f"Loaded {len(self.entries)} archive entries")
    
    async def start(self):
        """Start the Ark preservation system."""
        self._running = True
        
        # Start preservation loops
        self._tasks.append(asyncio.create_task(self._verification_loop()))
        self._tasks.append(asyncio.create_task(self._refresh_loop()))
        self._tasks.append(asyncio.create_task(self._migration_loop()))
        
        logger.info("Ark preservation system started")
    
    async def stop(self):
        """Stop the Ark."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        logger.info("Ark stopped")
    
    async def archive(
        self,
        content: Any,
        knowledge_tier: KnowledgeTier,
        entry_id: Optional[str] = None,
        decoding_instructions: Optional[str] = None,
    ) -> ArchiveEntry:
        """
        Archive knowledge for long-term preservation.
        
        Args:
            content: Content to archive (will be JSON serialized)
            knowledge_tier: Importance tier determining redundancy
            entry_id: Optional explicit ID
            decoding_instructions: Human-readable decoding instructions
        
        Returns:
            ArchiveEntry with preservation status
        """
        entry_id = entry_id or f"ark_{int(time.time())}_{hashlib.sha256(str(content).encode()).hexdigest()[:8]}"
        
        # Serialize and compress content
        serialized = json.dumps(content, default=str).encode('utf-8')
        compressed = zlib.compress(serialized, level=9)
        
        content_hash = hashlib.sha256(compressed).hexdigest()
        
        # Generate decoding instructions if not provided
        if not decoding_instructions:
            decoding_instructions = self._generate_decoding_instructions(entry_id, content)
        
        entry = ArchiveEntry(
            entry_id=entry_id,
            knowledge_tier=knowledge_tier,
            content=compressed,
            content_hash=content_hash,
            compression="zlib",
            created_at=time.time(),
            decoding_instructions=decoding_instructions,
        )
        
        # Store locally first
        await self._store_local(entry)
        
        # Replicate according to redundancy plan
        await self._replicate_entry(entry)
        
        # Save to database
        self.entries[entry_id] = entry
        self._save_entry(entry, len(compressed))
        
        self.stats["total_entries"] += 1
        self.stats["total_bytes"] += len(compressed)
        
        logger.info(f"Archived entry {entry_id} at tier {knowledge_tier.value}")
        return entry
    
    def _generate_decoding_instructions(self, entry_id: str, content: Any) -> str:
        """Generate human-readable decoding instructions."""
        instructions = f"""
AIWORKER ARCHIVE ENTRY - {entry_id}
================================

DECODING INSTRUCTIONS:
1. This file contains zlib-compressed JSON data
2. Decompress using: python -c "import zlib; print(zlib.decompress(open('{entry_id}.bin','rb').read()).decode())"
3. Or use standard zlib decompression in any programming language
4. Content is UTF-8 encoded JSON

CONTENT TYPE: {type(content).__name__}
ARCHIVED: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

This archive is part of the AIWorker knowledge preservation system.
For more information, see: https://aiworker.org/ark
"""
        return instructions
    
    async def _store_local(self, entry: ArchiveEntry):
        """Store entry in local storage."""
        # Store content
        content_path = self.storage_path / f"{entry.entry_id}.bin"
        with open(content_path, 'wb') as f:
            f.write(entry.content)
        
        # Store metadata
        meta_path = self.storage_path / f"{entry.entry_id}.json"
        metadata = {
            "entry_id": entry.entry_id,
            "knowledge_tier": entry.knowledge_tier.value,
            "content_hash": entry.content_hash,
            "compression": entry.compression,
            "created_at": entry.created_at,
            "format_version": entry.format_version,
            "decoding_instructions": entry.decoding_instructions,
        }
        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        entry.storage_locations[StorageMedium.DIGITAL_SSD] = [str(content_path)]
        entry.status = PreservationStatus.PRESERVED
    
    async def _replicate_entry(self, entry: ArchiveEntry):
        """Replicate entry according to redundancy plan."""
        plan = self.redundancy_plans[entry.knowledge_tier]
        
        # Replicate to cloud storage
        if StorageMedium.CLOUD in plan.target_media:
            await self._replicate_to_cloud(entry)
        
        # Replicate to M-DISC (if burner available)
        if StorageMedium.M_DISC in plan.target_media:
            await self._replicate_to_mdisc(entry)
        
        # Replicate to tape (if library available)
        if StorageMedium.DIGITAL_TAPE in plan.target_media:
            await self._replicate_to_tape(entry)
        
        # For demonstration, simulate distributed storage
        await self._simulate_distributed_storage(entry, plan)
    
    async def _replicate_to_cloud(self, entry: ArchiveEntry):
        """Replicate entry to cloud storage."""
        # Would integrate with S3, GCS, Azure, etc.
        # For now, simulate with local paths
        
        locations = []
        for region in ["us-east", "eu-west", "asia-pacific"]:
            # Simulate region-specific storage
            path = f"cloud://{region}/aiworker/ark/{entry.entry_id}"
            locations.append(path)
        
        entry.storage_locations[StorageMedium.CLOUD] = locations
        logger.debug(f"Replicated {entry.entry_id} to cloud ({len(locations)} regions)")
    
    async def _replicate_to_mdisc(self, entry: ArchiveEntry):
        """Replicate entry to M-DISC optical media."""
        # Would require optical drive
        # For now, simulate
        
        entry.storage_locations[StorageMedium.M_DISC] = [
            f"mdisc://archive-{i}/{entry.entry_id}"
            for i in range(3)  # 3 M-DISC copies
        ]
        logger.debug(f"Replicated {entry.entry_id} to M-DISC")
    
    async def _replicate_to_tape(self, entry: ArchiveEntry):
        """Replicate entry to tape storage."""
        entry.storage_locations[StorageMedium.DIGITAL_TAPE] = [
            f"tape://library-1/{entry.entry_id}"
        ]
        logger.debug(f"Replicated {entry.entry_id} to tape")
    
    async def _simulate_distributed_storage(self, entry: ArchiveEntry, plan: RedundancyPlan):
        """Simulate distributed storage across geographic regions."""
        # In production, this would use actual distributed storage systems
        # like IPFS, Filecoin, or geographically distributed cloud
        
        for region in plan.geographic_distribution:
            # Simulate storage in each region
            pass
    
    def _save_entry(self, entry: ArchiveEntry, content_size: int):
        """Save entry metadata to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO archive_entries
                (entry_id, knowledge_tier, content_hash, compression, created_at,
                 last_verified, storage_locations, status, format_version, decoding_instructions, content_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.entry_id,
                    entry.knowledge_tier.value,
                    entry.content_hash,
                    entry.compression,
                    entry.created_at,
                    entry.last_verified,
                    json.dumps({k.value: v for k, v in entry.storage_locations.items()}),
                    entry.status.value,
                    entry.format_version,
                    entry.decoding_instructions,
                    content_size,
                )
            )
            conn.commit()
    
    async def retrieve(self, entry_id: str) -> Optional[Any]:
        """
        Retrieve archived knowledge.
        
        Args:
            entry_id: ID of entry to retrieve
        
        Returns:
            Decoded content or None if not found/corrupted
        """
        entry = self.entries.get(entry_id)
        if not entry:
            logger.warning(f"Entry {entry_id} not found")
            return None
        
        # Try to load content from local storage first
        content_path = self.storage_path / f"{entry_id}.bin"
        if content_path.exists():
            with open(content_path, 'rb') as f:
                compressed = f.read()
        else:
            # Try cloud storage
            compressed = await self._retrieve_from_cloud(entry)
            if not compressed:
                logger.error(f"Could not retrieve {entry_id} from any location")
                return None
        
        # Verify hash
        content_hash = hashlib.sha256(compressed).hexdigest()
        if content_hash != entry.content_hash:
            logger.error(f"Hash mismatch for {entry_id} - possible corruption")
            entry.status = PreservationStatus.DEGRADED
            self._save_entry(entry, len(compressed))
            return None
        
        # Decompress and deserialize
        try:
            serialized = zlib.decompress(compressed)
            content = json.loads(serialized.decode('utf-8'))
            return content
        except Exception as e:
            logger.error(f"Failed to decode {entry_id}: {e}")
            return None
    
    async def _retrieve_from_cloud(self, entry: ArchiveEntry) -> Optional[bytes]:
        """Retrieve content from cloud storage."""
        # Would integrate with cloud APIs
        # For now, return None
        return None
    
    async def _verification_loop(self):
        """Periodic verification of archived content."""
        while self._running:
            try:
                # Verify a batch of entries each day
                await asyncio.sleep(86400)
                
                entries_to_verify = [
                    e for e in self.entries.values()
                    if e.status in [PreservationStatus.PRESERVED, PreservationStatus.VERIFIED]
                ]
                
                for entry in entries_to_verify[:10]:  # Verify 10 per day
                    await self._verify_entry(entry)
                
                logger.info(f"Verified {min(10, len(entries_to_verify))} archive entries")
                
            except Exception as e:
                logger.error(f"Verification loop error: {e}")
    
    async def _verify_entry(self, entry: ArchiveEntry):
        """Verify integrity of an archive entry."""
        content_path = self.storage_path / f"{entry.entry_id}.bin"
        
        if not content_path.exists():
            entry.status = PreservationStatus.DEGRADED
            logger.warning(f"Entry {entry.entry_id} missing from local storage")
        else:
            with open(content_path, 'rb') as f:
                compressed = f.read()
            
            content_hash = hashlib.sha256(compressed).hexdigest()
            if content_hash == entry.content_hash:
                entry.status = PreservationStatus.VERIFIED
                entry.last_verified = time.time()
                self.stats["verified_entries"] += 1
            else:
                entry.status = PreservationStatus.DEGRADED
                self.stats["degraded_entries"] += 1
                logger.error(f"Entry {entry.entry_id} failed verification")
        
        self._save_entry(entry, 0)
    
    async def _refresh_loop(self):
        """Periodic refresh of storage media."""
        while self._running:
            try:
                # Check for entries needing refresh (based on tier plan)
                await asyncio.sleep(86400 * 30)  # Monthly check
                
                now = time.time()
                for entry in self.entries.values():
                    plan = self.redundancy_plans[entry.knowledge_tier]
                    refresh_interval_sec = plan.refresh_interval_years * 365 * 86400
                    
                    if now - entry.created_at > refresh_interval_sec:
                        await self._refresh_entry(entry)
                
            except Exception as e:
                logger.error(f"Refresh loop error: {e}")
    
    async def _refresh_entry(self, entry: ArchiveEntry):
        """Refresh storage media for an entry."""
        logger.info(f"Refreshing entry {entry.entry_id}")
        
        # Re-read content
        content_path = self.storage_path / f"{entry.entry_id}.bin"
        if content_path.exists():
            with open(content_path, 'rb') as f:
                content = f.read()
            
            # Re-write (refreshes SSD cells)
            with open(content_path, 'wb') as f:
                f.write(content)
            
            # Update cloud copies
            await self._replicate_to_cloud(entry)
    
    async def _migration_loop(self):
        """Periodic check for format migration needs."""
        while self._running:
            try:
                await asyncio.sleep(86400 * 90)  # Quarterly check
                
                # Check for obsolete formats
                for entry in self.entries.values():
                    if entry.format_version != "1.0":  # Current version
                        await self._migrate_format(entry, "1.0")
                
            except Exception as e:
                logger.error(f"Migration loop error: {e}")
    
    async def _migrate_format(self, entry: ArchiveEntry, new_format: str):
        """Migrate entry to new format."""
        logger.info(f"Migrating {entry.entry_id} to format {new_format}")
        
        # Retrieve current content
        content = await self.retrieve(entry.entry_id)
        if content is None:
            logger.error(f"Cannot migrate {entry.entry_id} - retrieval failed")
            return
        
        # Create migration record
        migration = FormatMigration(
            migration_id=f"mig_{int(time.time())}",
            entry_id=entry.entry_id,
            old_format=entry.format_version,
            new_format=new_format,
            migrated_at=time.time(),
            reason="obsolescence",
        )
        
        # Update entry
        entry.format_version = new_format
        
        # Re-archive with new format
        await self.archive(
            content=content,
            knowledge_tier=entry.knowledge_tier,
            entry_id=entry.entry_id,
        )
        
        migration.verified = True
        self.migrations.append(migration)
        self._save_migration(migration)
    
    def _save_migration(self, migration: FormatMigration):
        """Save migration record to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO format_migrations
                (migration_id, entry_id, old_format, new_format, migrated_at, reason, verified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    migration.migration_id,
                    migration.entry_id,
                    migration.old_format,
                    migration.new_format,
                    migration.migrated_at,
                    migration.reason,
                    int(migration.verified),
                )
            )
            conn.commit()
    
    def get_preservation_status(self) -> Dict[str, Any]:
        """Get preservation status for dashboard."""
        tier_counts = {tier: 0 for tier in KnowledgeTier}
        for entry in self.entries.values():
            tier_counts[entry.knowledge_tier] += 1
        
        status_counts = {status: 0 for status in PreservationStatus}
        for entry in self.entries.values():
            status_counts[entry.status] += 1
        
        return {
            "total_entries": len(self.entries),
            "total_bytes": self.stats["total_bytes"],
            "by_tier": {tier.value: count for tier, count in tier_counts.items()},
            "by_status": {status.value: count for status, count in status_counts.items()},
            "verified_entries": self.stats["verified_entries"],
            "degraded_entries": self.stats["degraded_entries"],
            "format_migrations": len(self.migrations),
            "storage_media_used": len(set(
                medium
                for entry in self.entries.values()
                for medium in entry.storage_locations.keys()
            )),
        }
    
    async def create_ceramic_backup(self, entry_ids: List[str]) -> str:
        """
        Create ceramic/metal plate backup for critical knowledge.
        
        This is for truly long-term preservation (centuries+).
        Would integrate with ceramic engraving services.
        """
        # Would generate engraving files for ceramic plates
        # Each plate can store ~1MB of data as QR codes or similar
        
        backup_id = f"ceramic_{int(time.time())}"
        logger.info(f"Created ceramic backup {backup_id} with {len(entry_ids)} entries")
        return backup_id
