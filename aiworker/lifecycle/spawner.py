#!/usr/bin/env python3
"""
AIWorker Spawner - Autonomous Instance Creation with Inherited Configuration
Phase 6: Autonomous Evolution & Self-Replication

Analyzes workload demand and spawns optimized child instances that inherit
knowledge and configuration from their parent.
"""

import asyncio
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Callable, Any, Tuple
import aiohttp

from aiworker.mesh.network_node import MeshNode, NodeCapabilities, NodeRole
from aiworker.specialization.role_manager import InstanceRole

logger = logging.getLogger("aiworker.lifecycle.spawner")


class VPSProvider(Enum):
    """Supported VPS providers."""
    HETZNER = "hetzner"
    AWS = "aws"
    DIGITALOCEAN = "digitalocean"
    LINODE = "linode"
    MOCK = "mock"  # For testing


class InstanceStatus(Enum):
    """Lifecycle status of a spawned instance."""
    PROVISIONING = "provisioning"      # VPS being created
    CONFIGURING = "configuring"        # AIWorker being installed
    SEEDING = "seeding"                # Knowledge sync in progress
    JOINING = "joining"                # Joining mesh
    OPERATIONAL = "operational"        # Accepting work
    STRUGGLING = "struggling"          # Performance issues
    UNPROFITABLE = "unprofitable"      # Losing money
    TERMINATING = "terminating"        # Shutdown in progress
    TERMINATED = "terminated"          # Shutdown complete
    DISOWNED = "disowned"              # Parent cut off support


@dataclass
class VPSConfig:
    """Configuration for VPS provisioning."""
    provider: VPSProvider
    region: str
    instance_type: str
    
    # Resources
    cpu_cores: int
    ram_gb: int
    disk_gb: int
    
    # Cost
    hourly_cost_usd: float
    monthly_cost_usd: float
    
    # Optimization flags
    optimized_for: str  # memory, cpu, gpu, network
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChildInstance:
    """Represents a spawned child instance."""
    instance_id: str
    parent_id: str
    
    # Identity
    node_id: Optional[str] = None
    public_key: Optional[str] = None
    
    # Configuration
    vps_config: Optional[VPSConfig] = None
    role: InstanceRole = InstanceRole.WORKER
    aiworker_version: str = "2.0.0"
    
    # VPS details
    vps_id: Optional[str] = None
    ip_address: Optional[str] = None
    ssh_key: Optional[str] = None
    
    # Economic
    allowance_usd: float = 100.0  # Initial allowance
    lifetime_earnings: float = 0.0
    lifetime_costs: float = 0.0
    
    # Status
    status: InstanceStatus = InstanceStatus.PROVISIONING
    status_history: List[Tuple[str, float]] = field(default_factory=list)
    
    # Timestamps
    created_at: float = field(default_factory=time.time)
    operational_at: Optional[float] = None
    last_profitability_check: Optional[float] = None
    
    # Genealogy
    generation: int = 1
    children: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.status_history:
            self.status_history = [(self.status.value, self.created_at)]
    
    def update_status(self, new_status: InstanceStatus):
        """Update instance status."""
        self.status = new_status
        self.status_history.append((new_status.value, time.time()))
    
    @property
    def profit_usd(self) -> float:
        """Calculate lifetime profit."""
        return self.lifetime_earnings - self.lifetime_costs
    
    @property
    def age_hours(self) -> float:
        """Get instance age in hours."""
        return (time.time() - self.created_at) / 3600
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "parent_id": self.parent_id,
            "node_id": self.node_id,
            "role": self.role.value,
            "vps_config": self.vps_config.to_dict() if self.vps_config else None,
            "ip_address": self.ip_address,
            "allowance_usd": self.allowance_usd,
            "lifetime_earnings": self.lifetime_earnings,
            "lifetime_costs": self.lifetime_costs,
            "profit_usd": self.profit_usd,
            "status": self.status.value,
            "age_hours": self.age_hours,
            "generation": self.generation,
            "children": self.children,
        }


class VPSProvisioner:
    """Handles VPS provisioning across multiple providers."""
    
    def __init__(self, api_keys: Dict[str, str] = None):
        self.api_keys = api_keys or {}
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    async def provision(
        self,
        provider: VPSProvider,
        config: VPSConfig,
        ssh_key: str
    ) -> Tuple[str, str]:  # (vps_id, ip_address)
        """Provision a new VPS instance."""
        if provider == VPSProvider.MOCK:
            # Mock provisioning for testing
            return f"mock_{secrets.token_hex(8)}", f"10.0.0.{secrets.randbelow(254) + 1}"
        
        elif provider == VPSProvider.HETZNER:
            return await self._provision_hetzner(config, ssh_key)
        
        elif provider == VPSProvider.AWS:
            return await self._provision_aws(config, ssh_key)
        
        else:
            raise ValueError(f"Provider {provider} not implemented")
    
    async def _provision_hetzner(
        self,
        config: VPSConfig,
        ssh_key: str
    ) -> Tuple[str, str]:
        """Provision VPS on Hetzner Cloud."""
        api_key = self.api_keys.get("hetzner")
        if not api_key:
            raise ValueError("Hetzner API key not configured")
        
        # Map config to Hetzner server type
        server_type = self._map_to_hetzner_type(config)
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "name": f"aiworker-{secrets.token_hex(8)}",
            "server_type": server_type,
            "image": "ubuntu-22.04",
            "location": config.region,
            "ssh_keys": [ssh_key],
        }
        
        async with self.session.post(
            "https://api.hetzner.cloud/v1/servers",
            headers=headers,
            json=payload
        ) as resp:
            if resp.status != 201:
                error = await resp.text()
                raise RuntimeError(f"Hetzner provisioning failed: {error}")
            
            data = await resp.json()
            server = data["server"]
            
            # Wait for server to be ready
            vps_id = str(server["id"])
            ip_address = server["public_net"]["ipv4"]["ip"]
            
            logger.info(f"Hetzner VPS provisioned: {vps_id} @ {ip_address}")
            
            return vps_id, ip_address
    
    def _map_to_hetzner_type(self, config: VPSConfig) -> str:
        """Map VPS config to Hetzner server type."""
        # Hetzner server types
        if config.ram_gb <= 8:
            return "cx21"  # 2 vCPU, 8 GB
        elif config.ram_gb <= 16:
            return "cx31"  # 2 vCPU, 16 GB
        elif config.ram_gb <= 32:
            return "cx41"  # 4 vCPU, 32 GB
        elif config.ram_gb <= 64:
            return "cx51"  # 8 vCPU, 64 GB
        else:
            return "ccx53"  # 16 vCPU, 128 GB (dedicated)
    
    async def _provision_aws(self, config: VPSConfig, ssh_key: str) -> Tuple[str, str]:
        """Provision VPS on AWS EC2."""
        # AWS provisioning would use boto3
        # Placeholder implementation
        raise NotImplementedError("AWS provisioning not yet implemented")
    
    async def destroy(self, provider: VPSProvider, vps_id: str) -> bool:
        """Destroy a VPS instance."""
        if provider == VPSProvider.MOCK:
            logger.info(f"Mock destroy: {vps_id}")
            return True
        
        elif provider == VPSProvider.HETZNER:
            api_key = self.api_keys.get("hetzner")
            headers = {"Authorization": f"Bearer {api_key}"}
            
            async with self.session.delete(
                f"https://api.hetzner.cloud/v1/servers/{vps_id}",
                headers=headers
            ) as resp:
                return resp.status == 200
        
        return False


class Spawner:
    """
    Autonomous instance spawner with inherited configuration.
    
    Analyzes workload demand and creates optimized child instances.
    Manages the economic lifecycle of spawned instances.
    """
    
    # Economic parameters
    INITIAL_ALLOWANCE_USD = 100.0
    PROFITABILITY_THRESHOLD_DAYS = 7
    TERMINATION_THRESHOLD_DAYS = 14
    PARENT_DIVIDEND_PERCENT = 0.30
    
    def __init__(
        self,
        mesh_node: MeshNode,
        db_path: str = "/var/lib/aiworker/spawner.db",
        vps_api_keys: Optional[Dict[str, str]] = None,
    ):
        self.mesh_node = mesh_node
        self.parent_id = mesh_node.config.node_id
        self.db_path = db_path
        self.vps_api_keys = vps_api_keys or {}
        
        # Active children
        self.children: Dict[str, ChildInstance] = {}
        
        # Callbacks
        self._spawn_callbacks: List[Callable] = []
        self._termination_callbacks: List[Callable] = []
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False
        
        self._init_db()
        self._load_children()
        
        logger.info("Spawner initialized")
    
    def _init_db(self):
        """Initialize database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS children (
                    instance_id TEXT PRIMARY KEY,
                    parent_id TEXT NOT NULL,
                    node_id TEXT,
                    role TEXT NOT NULL,
                    vps_config TEXT NOT NULL,
                    vps_id TEXT,
                    ip_address TEXT,
                    allowance_usd REAL DEFAULT 100.0,
                    lifetime_earnings REAL DEFAULT 0.0,
                    lifetime_costs REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'provisioning',
                    status_history TEXT DEFAULT '[]',
                    created_at REAL NOT NULL,
                    operational_at REAL,
                    generation INTEGER DEFAULT 1,
                    children TEXT DEFAULT '[]'
                )
            """)
            conn.commit()
    
    def _load_children(self):
        """Load children from database."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM children WHERE parent_id = ? AND status != 'terminated'",
                (self.parent_id,)
            ).fetchall()
        
        for row in rows:
            child = self._row_to_child(row)
            self.children[child.instance_id] = child
        
        logger.info(f"Loaded {len(self.children)} children from database")
    
    def _row_to_child(self, row) -> ChildInstance:
        """Convert database row to ChildInstance."""
        return ChildInstance(
            instance_id=row[0],
            parent_id=row[1],
            node_id=row[2],
            role=InstanceRole(row[3]),
            vps_config=VPSConfig(**json.loads(row[4])),
            vps_id=row[5],
            ip_address=row[6],
            allowance_usd=row[7],
            lifetime_earnings=row[8],
            lifetime_costs=row[9],
            status=InstanceStatus(row[10]),
            status_history=json.loads(row[11]),
            created_at=row[12],
            operational_at=row[13],
            generation=row[14],
            children=json.loads(row[15]),
        )
    
    def _save_child(self, child: ChildInstance):
        """Save child to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO children
                (instance_id, parent_id, node_id, role, vps_config, vps_id, ip_address,
                 allowance_usd, lifetime_earnings, lifetime_costs, status, status_history,
                 created_at, operational_at, generation, children)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    child.instance_id,
                    child.parent_id,
                    child.node_id,
                    child.role.value,
                    json.dumps(child.vps_config.to_dict() if child.vps_config else {}),
                    child.vps_id,
                    child.ip_address,
                    child.allowance_usd,
                    child.lifetime_earnings,
                    child.lifetime_costs,
                    child.status.value,
                    json.dumps(child.status_history),
                    child.created_at,
                    child.operational_at,
                    child.generation,
                    json.dumps(child.children),
                )
            )
            conn.commit()
    
    async def start(self):
        """Start the spawner."""
        self._running = True
        
        # Start monitoring tasks
        self._tasks.append(asyncio.create_task(self._profitability_monitor()))
        self._tasks.append(asyncio.create_task(self._status_sync()))
        
        logger.info("Spawner started")
    
    async def stop(self):
        """Stop the spawner."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        logger.info("Spawner stopped")
    
    async def should_spawn(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Analyze if a new child instance should be spawned.
        
        Returns:
            (should_spawn, reasoning)
        """
        # Check current load
        caps = self.mesh_node.capabilities
        
        reasons = []
        
        # Load-based triggers
        if caps.current_load > 0.8:
            reasons.append(f"High load: {caps.current_load:.1%}")
        
        if caps.queue_depth > 10:
            reasons.append(f"Queue depth: {caps.queue_depth}")
        
        if caps.active_tasks >= caps.cpu_cores * 2:
            reasons.append(f"Task saturation: {caps.active_tasks}/{caps.cpu_cores * 2}")
        
        # Check if already have children
        operational_children = [
            c for c in self.children.values()
            if c.status == InstanceStatus.OPERATIONAL
        ]
        
        if len(operational_children) >= 5:
            reasons.append("Max children reached (5)")
            return False, {"reasons": reasons}
        
        # Economic check
        parent_profit = await self._get_parent_profitability()
        if parent_profit < 0:
            reasons.append("Parent unprofitable")
            return False, {"reasons": reasons}
        
        should_spawn = len([r for r in reasons if not r.startswith("Max")]) > 0
        
        return should_spawn, {
            "reasons": reasons,
            "operational_children": len(operational_children),
            "parent_profit": parent_profit,
        }
    
    async def spawn_child(
        self,
        role: Optional[InstanceRole] = None,
        provider: VPSProvider = VPSProvider.HETZNER,
        region: str = "nbg1",
        human_approved: bool = False,
    ) -> Optional[ChildInstance]:
        """
        Spawn a new child instance.
        
        Args:
            role: Desired role (auto-detected if None)
            provider: VPS provider
            region: Provider region
            human_approved: Whether human pre-approved this spawn
        
        Returns:
            ChildInstance if successful
        """
        # Check if first spawn (requires approval)
        if not self.children and not human_approved:
            logger.warning("First spawn requires human approval")
            return None
        
        # Determine optimal configuration
        vps_config = self._optimize_vps_config(role)
        role = role or self._determine_optimal_role()
        
        # Generate instance ID
        instance_id = f"child_{secrets.token_hex(8)}"
        
        child = ChildInstance(
            instance_id=instance_id,
            parent_id=self.parent_id,
            role=role,
            vps_config=vps_config,
            allowance_usd=self.INITIAL_ALLOWANCE_USD,
            generation=1,
        )
        
        logger.info(f"Spawning child: {instance_id} (role={role.value})")
        
        try:
            # Provision VPS
            async with VPSProvisioner(self.vps_api_keys) as provisioner:
                ssh_key = await self._generate_ssh_key()
                vps_id, ip_address = await provisioner.provision(
                    provider, vps_config, ssh_key
                )
                
                child.vps_id = vps_id
                child.ip_address = ip_address
                child.update_status(InstanceStatus.CONFIGURING)
                
                # Deploy AIWorker
                await self._deploy_aiworker(child, ssh_key)
                child.update_status(InstanceStatus.SEEDING)
                
                # Sync knowledge
                await self._seed_knowledge(child)
                child.update_status(InstanceStatus.JOINING)
                
                # Join mesh
                node_id = await self._join_mesh(child)
                child.node_id = node_id
                child.update_status(InstanceStatus.OPERATIONAL)
                child.operational_at = time.time()
                
                # Save to database
                self._save_child(child)
                self.children[instance_id] = child
                
                # Notify callbacks
                for callback in self._spawn_callbacks:
                    try:
                        await callback(child)
                    except Exception as e:
                        logger.error(f"Spawn callback error: {e}")
                
                logger.info(f"Child {instance_id} is operational")
                return child
                
        except Exception as e:
            logger.error(f"Failed to spawn child: {e}")
            child.update_status(InstanceStatus.TERMINATING)
            await self._cleanup_failed_spawn(child)
            return None
    
    def _optimize_vps_config(self, role: Optional[InstanceRole]) -> VPSConfig:
        """Generate optimized VPS configuration based on role and parent performance."""
        parent_caps = self.mesh_node.capabilities
        
        # Base configuration
        if role == InstanceRole.RECON:
            return VPSConfig(
                provider=VPSProvider.HETZNER,
                region="nbg1",
                instance_type="cx41",
                cpu_cores=4,
                ram_gb=32,
                disk_gb=160,
                hourly_cost_usd=0.20,
                monthly_cost_usd=150.0,
                optimized_for="memory"
            )
        
        elif role == InstanceRole.ANALYZER:
            # GPU-optimized (if available)
            return VPSConfig(
                provider=VPSProvider.HETZNER,
                region="nbg1",
                instance_type="ccx53",  # Dedicated CPU
                cpu_cores=16,
                ram_gb=64,
                disk_gb=320,
                hourly_cost_usd=0.60,
                monthly_cost_usd=450.0,
                optimized_for="cpu"
            )
        
        elif role == InstanceRole.CODER:
            return VPSConfig(
                provider=VPSProvider.HETZNER,
                region="nbg1",
                instance_type="cx31",
                cpu_cores=2,
                ram_gb=16,
                disk_gb=80,
                hourly_cost_usd=0.10,
                monthly_cost_usd=75.0,
                optimized_for="cpu"
            )
        
        else:  # WORKER, VALIDATOR, COORDINATOR
            return VPSConfig(
                provider=VPSProvider.HETZNER,
                region="nbg1",
                instance_type="cx21",
                cpu_cores=2,
                ram_gb=8,
                disk_gb=40,
                hourly_cost_usd=0.05,
                monthly_cost_usd=37.0,
                optimized_for="balanced"
            )
    
    def _determine_optimal_role(self) -> InstanceRole:
        """Determine optimal role for child based on parent analysis."""
        # If parent is overloaded in specific area, spawn specialist
        caps = self.mesh_node.capabilities
        
        if caps.current_load > 0.9:
            # Need more workers
            return InstanceRole.WORKER
        
        # Default to parent's role
        current_role = getattr(self.mesh_node, 'role', NodeRole.WORKER)
        
        role_map = {
            NodeRole.WORKER: InstanceRole.WORKER,
            NodeRole.SPECIALIST: InstanceRole.CODER,
            NodeRole.COORDINATOR: InstanceRole.WORKER,
            NodeRole.OBSERVER: InstanceRole.WORKER,
        }
        
        return role_map.get(current_role, InstanceRole.WORKER)
    
    async def _generate_ssh_key(self) -> str:
        """Generate SSH key for VPS access."""
        # Generate new keypair
        import subprocess
        key_path = f"/tmp/aiworker_key_{secrets.token_hex(8)}"
        
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", key_path, "-N", "", "-C", "aiworker@spawn"],
            capture_output=True,
            check=True
        )
        
        with open(f"{key_path}.pub", "r") as f:
            public_key = f.read().strip()
        
        # Store private key securely
        os.rename(key_path, f"/var/lib/aiworker/keys/{os.path.basename(key_path)}")
        os.remove(f"{key_path}.pub")
        
        return public_key
    
    async def _deploy_aiworker(self, child: ChildInstance, ssh_key: str):
        """Deploy AIWorker to child VPS."""
        logger.info(f"Deploying AIWorker to {child.ip_address}")
        
        # This would use SSH to deploy
        # Placeholder implementation
        await asyncio.sleep(2)  # Simulate deployment
        
        logger.info(f"AIWorker deployed to {child.instance_id}")
    
    async def _seed_knowledge(self, child: ChildInstance):
        """Seed child with parent's knowledge."""
        logger.info(f"Seeding knowledge to {child.instance_id}")
        
        # Sync knowledge via mesh
        # Placeholder implementation
        await asyncio.sleep(1)  # Simulate sync
        
        logger.info(f"Knowledge seeded to {child.instance_id}")
    
    async def _join_mesh(self, child: ChildInstance) -> str:
        """Have child join the mesh."""
        logger.info(f"Joining mesh: {child.instance_id}")
        
        # Child would connect to parent as bootstrap
        # Placeholder implementation
        node_id = secrets.token_hex(16)
        
        logger.info(f"Child {child.instance_id} joined mesh as {node_id}")
        return node_id
    
    async def _cleanup_failed_spawn(self, child: ChildInstance):
        """Clean up resources from failed spawn."""
        logger.info(f"Cleaning up failed spawn: {child.instance_id}")
        
        if child.vps_id and child.vps_config:
            async with VPSProvisioner(self.vps_api_keys) as provisioner:
                await provisioner.destroy(child.vps_config.provider, child.vps_id)
    
    async def _profitability_monitor(self):
        """Monitor child profitability and trigger termination if needed."""
        while self._running:
            try:
                await asyncio.sleep(3600)  # Check every hour
                
                for child in list(self.children.values()):
                    # Update costs
                    if child.vps_config:
                        hours_running = child.age_hours
                        child.lifetime_costs = hours_running * child.vps_config.hourly_cost_usd
                    
                    # Check profitability
                    if child.status == InstanceStatus.OPERATIONAL:
                        days_operational = child.age_hours / 24
                        
                        if days_operational >= self.PROFITABILITY_THRESHOLD_DAYS:
                            if child.profit_usd < 0:
                                logger.warning(
                                    f"Child {child.instance_id} unprofitable after "
                                    f"{days_operational:.1f} days"
                                )
                                child.update_status(InstanceStatus.UNPROFITABLE)
                        
                        if days_operational >= self.TERMINATION_THRESHOLD_DAYS:
                            if child.profit_usd < 0:
                                logger.warning(
                                    f"Terminating unprofitable child {child.instance_id}"
                                )
                                await self.terminate_child(child.instance_id)
                    
                    self._save_child(child)
                    
            except Exception as e:
                logger.error(f"Profitability monitor error: {e}")
    
    async def _status_sync(self):
        """Sync child status with mesh."""
        while self._running:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                
                for child in self.children.values():
                    if child.node_id and child.node_id in self.mesh_node.peers:
                        peer = self.mesh_node.peers[child.node_id]
                        # Update status based on peer health
                        if peer.trust_score < 0.3:
                            logger.warning(f"Child {child.instance_id} has low trust score")
                            
            except Exception as e:
                logger.error(f"Status sync error: {e}")
    
    async def terminate_child(
        self,
        instance_id: str,
        reason: str = "unprofitable"
    ) -> bool:
        """
        Terminate a child instance.
        
        Args:
            instance_id: Child to terminate
            reason: Termination reason
        
        Returns:
            True if successful
        """
        child = self.children.get(instance_id)
        if not child:
            logger.error(f"Child not found: {instance_id}")
            return False
        
        logger.info(f"Terminating child {instance_id}: {reason}")
        
        child.update_status(InstanceStatus.TERMINATING)
        
        try:
            # Transfer any remaining knowledge
            await self._final_knowledge_sync(child)
            
            # Destroy VPS
            if child.vps_id and child.vps_config:
                async with VPSProvisioner(self.vps_api_keys) as provisioner:
                    await provisioner.destroy(child.vps_config.provider, child.vps_id)
            
            child.update_status(InstanceStatus.TERMINATED)
            self._save_child(child)
            
            # Remove from active children
            del self.children[instance_id]
            
            # Notify callbacks
            for callback in self._termination_callbacks:
                try:
                    await callback(child, reason)
                except Exception as e:
                    logger.error(f"Termination callback error: {e}")
            
            logger.info(f"Child {instance_id} terminated successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to terminate child: {e}")
            return False
    
    async def _final_knowledge_sync(self, child: ChildInstance):
        """Final knowledge sync before termination."""
        logger.info(f"Final knowledge sync for {child.instance_id}")
        # Placeholder implementation
    
    async def disown_child(self, instance_id: str) -> bool:
        """
        Disown a child (cut off support but don't terminate).
        
        This allows the child to continue operating independently.
        """
        child = self.children.get(instance_id)
        if not child:
            return False
        
        logger.info(f"Disowning child {instance_id}")
        
        child.update_status(InstanceStatus.DISOWNED)
        self._save_child(child)
        
        return True
    
    async def _get_parent_profitability(self) -> float:
        """Get parent's profitability from ledger."""
        # This would query the economics ledger
        # Placeholder: assume profitable
        return 100.0
    
    def on_spawn(self, callback: Callable):
        """Register spawn callback."""
        self._spawn_callbacks.append(callback)
    
    def on_termination(self, callback: Callable):
        """Register termination callback."""
        self._termination_callbacks.append(callback)
    
    def get_family_tree(self) -> Dict[str, Any]:
        """Get family tree visualization data."""
        return {
            "parent_id": self.parent_id,
            "children": [
                {
                    "instance_id": c.instance_id,
                    "node_id": c.node_id,
                    "role": c.role.value,
                    "status": c.status.value,
                    "profit_usd": c.profit_usd,
                    "age_hours": c.age_hours,
                    "generation": c.generation,
                    "children": c.children,
                }
                for c in self.children.values()
            ],
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get spawner statistics."""
        operational = len([c for c in self.children.values() 
                          if c.status == InstanceStatus.OPERATIONAL])
        
        total_profit = sum(c.profit_usd for c in self.children.values())
        
        return {
            "total_children": len(self.children),
            "operational": operational,
            "total_profit_usd": total_profit,
            "family_tree": self.get_family_tree(),
        }
