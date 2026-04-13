#!/usr/bin/env python3
"""
AIWorker Role Manager - Dynamic Specialization Management
Phase 5: Ecosystem Expansion & Multi-Instance Coordination

Manages dynamic specialization of AIWorker instances based on hardware
capabilities and performance metrics. Enables automatic role switching
and optimization for the mesh ecosystem.
"""

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Callable, Any, Tuple
from collections import defaultdict
import threading

import psutil

from aiworker.mesh.network_node import MeshNode, NodeRole, NodeCapabilities, MessageType, MeshMessage

logger = logging.getLogger("aiworker.specialization.role_manager")


class InstanceRole(Enum):
    """
    Mutually exclusive roles for AIWorker instances.
    
    Each instance can only have one role at a time, but can switch
    based on performance and mesh needs.
    """
    RECON = "recon"           # Optimized for enumeration, large memory for wordlists
    WORKER = "worker"
    CODER = "coder"           # Optimized for patch generation, fast model inference
    ANALYZER = "analyzer"     # Deep inspection, multiple models cached
    VALIDATOR = "validator"   # Safety cage specialist, conservative, high security
    COORDINATOR = "coordinator"  # Task distribution, minimal other work


class RoleRequirement(Enum):
    """Hardware requirements for each role."""
    RECON_MIN_RAM = 16        # GB - needs memory for wordlists
    CODER_MIN_RAM = 8         # GB - moderate memory needs
    ANALYZER_MIN_RAM = 32     # GB - multiple models
    ANALYZER_REQUIRES_GPU = True
    VALIDATOR_MIN_RAM = 8     # GB - conservative
    COORDINATOR_MIN_RAM = 4   # GB - minimal processing


@dataclass
class RolePerformance:
    """Performance metrics for a role."""
    role: InstanceRole
    
    # Task metrics
    tasks_accepted: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    
    # Quality metrics
    success_rate: float = 0.0
    avg_completion_time: float = 0.0
    quality_score: float = 0.0
    
    # Resource metrics
    avg_memory_usage: float = 0.0
    avg_cpu_usage: float = 0.0
    
    # Timestamps
    first_assigned: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    
    def update_success_rate(self):
        """Recalculate success rate."""
        total = self.tasks_completed + self.tasks_failed
        if total > 0:
            self.success_rate = self.tasks_completed / total


@dataclass
class RoleConfig:
    """Configuration for a role."""
    role: InstanceRole
    enabled: bool = True
    
    # Resource allocation
    max_concurrent_tasks: int = 3
    max_memory_gb: int = 16
    
    # Model configuration
    models_to_cache: List[str] = field(default_factory=list)
    model_quantization: str = "int8"
    
    # Work types
    accepted_task_types: List[str] = field(default_factory=list)
    
    # Auto-switch settings
    min_success_rate: float = 0.7
    switch_after_failures: int = 5


@dataclass
class HardwareProfile:
    """Detected hardware capabilities."""
    total_ram_gb: int = 0
    available_ram_gb: int = 0
    cpu_cores: int = 0
    cpu_frequency_mhz: float = 0.0
    
    # GPU
    has_gpu: bool = False
    gpu_name: str = ""
    gpu_vram_gb: int = 0
    gpu_compute_capability: float = 0.0
    
    # Storage
    disk_read_mbps: float = 0.0
    disk_write_mbps: float = 0.0
    
    # Network
    network_mbps: float = 1000.0
    
    # Detection timestamp
    detected_at: float = field(default_factory=time.time)
    
    def meets_requirements(self, role: InstanceRole) -> Tuple[bool, List[str]]:
        """Check if hardware meets role requirements."""
        failures = []
        
        if role == InstanceRole.RECON:
            if self.total_ram_gb < RoleRequirement.RECON_MIN_RAM.value:
                failures.append(f"RECON requires {RoleRequirement.RECON_MIN_RAM.value}GB RAM")
            if self.disk_read_mbps < 100:
                failures.append("RECON benefits from fast disk for wordlists")
        
        elif role == InstanceRole.CODER:
            if self.total_ram_gb < RoleRequirement.CODER_MIN_RAM.value:
                failures.append(f"CODER requires {RoleRequirement.CODER_MIN_RAM.value}GB RAM")
        
        elif role == InstanceRole.ANALYZER:
            if self.total_ram_gb < RoleRequirement.ANALYZER_MIN_RAM.value:
                failures.append(f"ANALYZER requires {RoleRequirement.ANALYZER_MIN_RAM.value}GB RAM")
            if RoleRequirement.ANALYZER_REQUIRES_GPU.value and not self.has_gpu:
                failures.append("ANALYZER benefits from GPU acceleration")
        
        elif role == InstanceRole.VALIDATOR:
            if self.total_ram_gb < RoleRequirement.VALIDATOR_MIN_RAM.value:
                failures.append(f"VALIDATOR requires {RoleRequirement.VALIDATOR_MIN_RAM.value}GB RAM")
        
        elif role == InstanceRole.COORDINATOR:
            if self.total_ram_gb < RoleRequirement.COORDINATOR_MIN_RAM.value:
                failures.append(f"COORDINATOR requires {RoleRequirement.COORDINATOR_MIN_RAM.value}GB RAM")
        
        return len(failures) == 0, failures


class PerformanceTracker:
    """Tracks performance metrics for role evaluation."""
    
    def __init__(self, db_path: str = "/var/lib/aiworker/role_performance.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        """Initialize database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS role_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    task_id TEXT,
                    task_type TEXT,
                    success BOOLEAN,
                    completion_time REAL,
                    memory_usage_mb REAL,
                    cpu_usage_percent REAL,
                    quality_score REAL,
                    timestamp REAL NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_role_perf_role ON role_performance(role)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_role_perf_time ON role_performance(timestamp)
            """)
            
            conn.commit()
    
    def record_task(
        self,
        role: InstanceRole,
        task_id: str,
        task_type: str,
        success: bool,
        completion_time: float,
        memory_usage_mb: float = 0.0,
        cpu_usage_percent: float = 0.0,
        quality_score: float = 0.0
    ):
        """Record task completion metrics."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO role_performance 
                    (role, task_id, task_type, success, completion_time,
                     memory_usage_mb, cpu_usage_percent, quality_score, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        role.value,
                        task_id,
                        task_type,
                        success,
                        completion_time,
                        memory_usage_mb,
                        cpu_usage_percent,
                        quality_score,
                        time.time()
                    )
                )
                conn.commit()
    
    def get_role_performance(
        self,
        role: InstanceRole,
        since: Optional[float] = None
    ) -> RolePerformance:
        """Get aggregated performance for a role."""
        since = since or time.time() - 86400  # Default to last 24 hours
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Get task counts
                row = conn.execute(
                    """
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed,
                        AVG(completion_time) as avg_time,
                        AVG(memory_usage_mb) as avg_memory,
                        AVG(cpu_usage_percent) as avg_cpu,
                        AVG(quality_score) as avg_quality
                    FROM role_performance
                    WHERE role = ? AND timestamp > ?
                    """,
                    (role.value, since)
                ).fetchone()
        
        perf = RolePerformance(role=role)
        
        if row:
            perf.tasks_accepted = row[0] or 0
            perf.tasks_completed = row[1] or 0
            perf.tasks_failed = row[2] or 0
            perf.avg_completion_time = row[3] or 0.0
            perf.avg_memory_usage = row[4] or 0.0
            perf.avg_cpu_usage = row[5] or 0.0
            perf.quality_score = row[6] or 0.0
            perf.update_success_rate()
        
        return perf
    
    def get_all_performance(
        self,
        since: Optional[float] = None
    ) -> Dict[InstanceRole, RolePerformance]:
        """Get performance for all roles."""
        return {
            role: self.get_role_performance(role, since)
            for role in InstanceRole
        }


class RoleManager:
    """
    Dynamic specialization manager for AIWorker instances.
    
    Features:
    - Auto-detect hardware capabilities
    - Track performance by role
    - Suggest or auto-switch roles
    - Coordinate with mesh for role distribution
    """
    
    # Success rate threshold for role switching
    SUCCESS_RATE_THRESHOLD = 0.7
    
    # Minimum time in role before switching (hours)
    MIN_ROLE_TIME_HOURS = 1
    
    # Performance evaluation window (hours)
    EVALUATION_WINDOW_HOURS = 24
    
    def __init__(
        self,
        mesh_node: MeshNode,
        tracker: Optional[PerformanceTracker] = None,
        auto_switch: bool = False  # Require safety cage approval by default
    ):
        self.mesh_node = mesh_node
        self.node_id = mesh_node.config.node_id
        self.tracker = tracker or PerformanceTracker()
        self.auto_switch = auto_switch
        
        # Current state
        self.current_role: InstanceRole = InstanceRole(mesh_node.config.role)
        self.hardware = self._detect_hardware()
        self.role_config = self._get_role_config(self.current_role)
        
        # Role history
        self.role_history: List[Tuple[InstanceRole, float]] = [(self.current_role, time.time())]
        
        # Switch approval
        self._pending_switch: Optional[InstanceRole] = None
        self._switch_callbacks: List[Callable] = []
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False
        
        # Update mesh with role
        self._update_mesh_role()
        
        logger.info(f"RoleManager initialized: role={self.current_role.value}")
    
    def _detect_hardware(self) -> HardwareProfile:
        """Auto-detect hardware capabilities."""
        profile = HardwareProfile()
        
        # Memory
        mem = psutil.virtual_memory()
        profile.total_ram_gb = mem.total // (1024**3)
        profile.available_ram_gb = mem.available // (1024**3)
        
        # CPU
        profile.cpu_cores = psutil.cpu_count(logical=True)
        try:
            freq = psutil.cpu_freq()
            if freq:
                profile.cpu_frequency_mhz = freq.current
        except Exception:
            pass
        
        # GPU detection
        try:
            import torch
            if torch.cuda.is_available():
                profile.has_gpu = True
                profile.gpu_name = torch.cuda.get_device_name(0)
                profile.gpu_vram_gb = torch.cuda.get_device_properties(0).total_memory // (1024**3)
                profile.gpu_compute_capability = float(
                    f"{torch.cuda.get_device_capability(0)[0]}."
                    f"{torch.cuda.get_device_capability(0)[1]}"
                )
        except ImportError:
            pass
        
        # Disk speed estimation
        try:
            import tempfile
            start = time.time()
            with tempfile.NamedTemporaryFile(delete=False) as f:
                f.write(b"0" * (1024 * 1024))  # 1MB
            elapsed = time.time() - start
            profile.disk_write_mbps = 1.0 / elapsed if elapsed > 0 else 100
        except Exception:
            pass
        
        logger.info(f"Hardware detected: {profile.total_ram_gb}GB RAM, "
                   f"GPU={profile.has_gpu}, Cores={profile.cpu_cores}")
        
        return profile
    
    def _get_role_config(self, role: InstanceRole) -> RoleConfig:
        """Get configuration for a role."""
        configs = {
            InstanceRole.RECON: RoleConfig(
                role=role,
                max_concurrent_tasks=5,
                max_memory_gb=24,
                accepted_task_types=["subdomain_enum", "port_scan", "service_ident"],
            ),
            InstanceRole.CODER: RoleConfig(
                role=role,
                max_concurrent_tasks=3,
                max_memory_gb=16,
                models_to_cache=["codegen", "patch_gen"],
                accepted_task_types=["patch_gen", "code_review", "exploit_dev"],
            ),
            InstanceRole.ANALYZER: RoleConfig(
                role=role,
                max_concurrent_tasks=2,
                max_memory_gb=28,
                models_to_cache=["deep_analyzer", "vuln_detect", "pattern_match"],
                model_quantization="int4",
                accepted_task_types=["deep_analyze", "vuln_confirm", "impact_assess"],
            ),
            InstanceRole.VALIDATOR: RoleConfig(
                role=role,
                max_concurrent_tasks=10,
                max_memory_gb=8,
                accepted_task_types=["safety_check", "patch_validate", "policy_check"],
            ),
            InstanceRole.COORDINATOR: RoleConfig(
                role=role,
                max_concurrent_tasks=1,
                max_memory_gb=4,
                accepted_task_types=["task_route", "health_check"],
            ),
        }
        
        return configs.get(role, RoleConfig(role=role))
    
    def _update_mesh_role(self):
        """Update mesh node with current role."""
        self.mesh_node.role = NodeRole(self.current_role.value.upper())
        self.mesh_node.capabilities.specialization = self.current_role.value
    
    async def start(self):
        """Start the role manager."""
        self._running = True
        
        # Start performance monitoring
        self._tasks.append(asyncio.create_task(self._performance_monitor()))
        
        # Start role evaluation
        if self.auto_switch:
            self._tasks.append(asyncio.create_task(self._role_evaluation_loop()))
        
        logger.info("RoleManager started")
    
    async def stop(self):
        """Stop the role manager."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        logger.info("RoleManager stopped")
    
    async def _performance_monitor(self):
        """Monitor resource usage during task execution."""
        while self._running:
            try:
                await asyncio.sleep(60)
                
                # Update hardware profile
                self.hardware = self._detect_hardware()
                
                # Update mesh capabilities
                self.mesh_node.capabilities = self._capabilities_from_hardware()
                
            except Exception as e:
                logger.error(f"Performance monitor error: {e}")
    
    def _capabilities_from_hardware(self) -> NodeCapabilities:
        """Convert hardware profile to node capabilities."""
        return NodeCapabilities(
            ram_gb=self.hardware.total_ram_gb,
            cpu_cores=self.hardware.cpu_cores,
            has_gpu=self.hardware.has_gpu,
            gpu_vram_gb=self.hardware.gpu_vram_gb,
            disk_speed_mbps=int(self.hardware.disk_write_mbps),
            network_mbps=int(self.hardware.network_mbps),
            specialization=self.current_role.value,
        )
    
    async def _role_evaluation_loop(self):
        """Periodically evaluate role performance and suggest switches."""
        while self._running:
            try:
                await asyncio.sleep(3600)  # Every hour
                
                await self.evaluate_role()
                
            except Exception as e:
                logger.error(f"Role evaluation error: {e}")
    
    async def evaluate_role(self) -> Optional[InstanceRole]:
        """
        Evaluate current role performance and suggest switch if needed.
        
        Returns:
            Suggested new role, or None if current role is optimal
        """
        # Get current performance
        perf = self.tracker.get_role_performance(self.current_role)
        
        # Check if we've been in role long enough
        time_in_role = time.time() - self.role_history[-1][1]
        if time_in_role < self.MIN_ROLE_TIME_HOURS * 3600:
            return None
        
        # Check success rate
        if perf.success_rate < self.SUCCESS_RATE_THRESHOLD:
            logger.warning(
                f"Low success rate for {self.current_role.value}: "
                f"{perf.success_rate:.2%}"
            )
            
            # Suggest alternative role
            suggested = self._suggest_alternative_role()
            if suggested and suggested != self.current_role:
                logger.info(f"Suggested role switch: {self.current_role.value} -> {suggested.value}")
                
                if self.auto_switch:
                    await self.switch_role(suggested)
                else:
                    self._pending_switch = suggested
                    await self._notify_switch_suggestion(suggested, perf)
                
                return suggested
        
        # Check mesh needs
        mesh_suggestion = self._check_mesh_needs()
        if mesh_suggestion and mesh_suggestion != self.current_role:
            logger.info(f"Mesh suggests role switch to {mesh_suggestion.value}")
            
            if self.auto_switch:
                await self.switch_role(mesh_suggestion)
            else:
                self._pending_switch = mesh_suggestion
            
            return mesh_suggestion
        
        return None
    
    def _suggest_alternative_role(self) -> Optional[InstanceRole]:
        """Suggest an alternative role based on hardware and performance."""
        # Get performance for all roles
        all_perf = self.tracker.get_all_performance()
        
        # Filter to roles we can run
        viable_roles = []
        for role in InstanceRole:
            if role == self.current_role:
                continue
            
            meets, failures = self.hardware.meets_requirements(role)
            if meets:
                viable_roles.append(role)
        
        if not viable_roles:
            return None
        
        # Score each viable role
        best_role = None
        best_score = float('-inf')
        
        for role in viable_roles:
            perf = all_perf[role]
            
            # Score based on success rate and task volume
            score = perf.success_rate * 100 + perf.tasks_completed
            
            # Bonus for roles that match our hardware
            if role == InstanceRole.ANALYZER and self.hardware.has_gpu:
                score += 50
            if role == InstanceRole.RECON and self.hardware.total_ram_gb >= 32:
                score += 30
            
            if score > best_score:
                best_score = score
                best_role = role
        
        return best_role
    
    def _check_mesh_needs(self) -> Optional[InstanceRole]:
        """Check if mesh needs more of a specific role."""
        # Count roles in mesh
        role_counts = defaultdict(int)
        
        for peer in self.mesh_node.peers.values():
            try:
                role = InstanceRole(peer.capabilities.specialization)
                role_counts[role] += 1
            except ValueError:
                pass
        
        # Add self
        role_counts[self.current_role] += 1
        
        # Find underrepresented roles
        total = len(self.mesh_node.peers) + 1
        
        # VALIDATORs should be ~20% of mesh
        if role_counts[InstanceRole.VALIDATOR] < total * 0.15:
            meets, _ = self.hardware.meets_requirements(InstanceRole.VALIDATOR)
            if meets:
                return InstanceRole.VALIDATOR
        
        # COORDINATORs should be ~10% of mesh (or 1 for small meshes)
        if role_counts[InstanceRole.COORDINATOR] < max(1, total * 0.1):
            meets, _ = self.hardware.meets_requirements(InstanceRole.COORDINATOR)
            if meets:
                return InstanceRole.COORDINATOR
        
        return None
    
    async def switch_role(
        self,
        new_role: InstanceRole,
        force: bool = False
    ) -> bool:
        """
        Switch to a new role.
        
        Args:
            new_role: Role to switch to
            force: Skip safety checks
        
        Returns:
            True if switch was successful
        """
        # Validate switch
        if new_role == self.current_role:
            return True
        
        # Check hardware requirements
        meets, failures = self.hardware.meets_requirements(new_role)
        if not meets and not force:
            logger.error(f"Cannot switch to {new_role.value}: {failures}")
            return False
        
        logger.info(f"Switching role: {self.current_role.value} -> {new_role.value}")
        
        # Graceful shutdown of current role
        await self._graceful_shutdown()
        
        # Update role
        old_role = self.current_role
        self.current_role = new_role
        self.role_config = self._get_role_config(new_role)
        self.role_history.append((new_role, time.time()))
        
        # Update mesh
        self._update_mesh_role()
        
        # Announce role change
        await self._announce_role_change(old_role, new_role)
        
        # Reset telemetry baselines
        await self._reset_baselines()
        
        # Notify callbacks
        for callback in self._switch_callbacks:
            try:
                await callback(old_role, new_role)
            except Exception as e:
                logger.error(f"Switch callback error: {e}")
        
        logger.info(f"Role switch complete: {new_role.value}")
        
        return True
    
    async def _graceful_shutdown(self):
        """Gracefully shutdown current role."""
        logger.debug(f"Gracefully shutting down {self.current_role.value}")
        
        # Wait for current tasks to complete
        # (Actual implementation would check task queue)
        await asyncio.sleep(2)
    
    async def _announce_role_change(self, old_role: InstanceRole, new_role: InstanceRole):
        """Announce role change to mesh."""
        message = MeshMessage(
            msg_type=MessageType.ANNOUNCE,
            sender_id=self.node_id,
            payload={
                "role_change": {
                    "from": old_role.value,
                    "to": new_role.value,
                    "timestamp": time.time(),
                },
                "capabilities": self.mesh_node.capabilities.to_dict(),
            }
        )
        
        await self.mesh_node.broadcast(message)
    
    async def _reset_baselines(self):
        """Reset telemetry baselines for new role."""
        logger.debug("Resetting telemetry baselines")
        # Implementation would reset performance baselines
    
    async def _notify_switch_suggestion(self, suggested: InstanceRole, perf: RolePerformance):
        """Notify about role switch suggestion."""
        logger.info(
            f"ROLE_SWITCH_SUGGESTION: Current={self.current_role.value}, "
            f"Suggested={suggested.value}, SuccessRate={perf.success_rate:.2%}"
        )
        
        # This would integrate with safety cage for approval
    
    def approve_switch(self) -> bool:
        """Approve a pending role switch (called by safety cage)."""
        if self._pending_switch:
            asyncio.create_task(self.switch_role(self._pending_switch))
            self._pending_switch = None
            return True
        return False
    
    def on_role_switch(self, callback: Callable):
        """Register callback for role switches."""
        self._switch_callbacks.append(callback)
    
    def get_eligible_roles(self) -> List[InstanceRole]:
        """Get list of roles this instance is eligible for."""
        eligible = []
        
        for role in InstanceRole:
            meets, _ = self.hardware.meets_requirements(role)
            if meets:
                eligible.append(role)
        
        return eligible
    
    def get_stats(self) -> Dict[str, Any]:
        """Get role manager statistics."""
        perf = self.tracker.get_role_performance(self.current_role)
        
        return {
            "current_role": self.current_role.value,
            "role_since": self.role_history[-1][1],
            "role_history": [(r.value, t) for r, t in self.role_history],
            "hardware": {
                "ram_gb": self.hardware.total_ram_gb,
                "has_gpu": self.hardware.has_gpu,
                "gpu_vram_gb": self.hardware.gpu_vram_gb,
                "cpu_cores": self.hardware.cpu_cores,
            },
            "performance": {
                "success_rate": perf.success_rate,
                "tasks_completed": perf.tasks_completed,
                "tasks_failed": perf.tasks_failed,
                "avg_completion_time": perf.avg_completion_time,
            },
            "eligible_roles": [r.value for r in self.get_eligible_roles()],
            "pending_switch": self._pending_switch.value if self._pending_switch else None,
        }


# Convenience functions
async def create_role_manager(
    mesh_node: MeshNode,
    auto_switch: bool = False
) -> RoleManager:
    """Create and start a role manager."""
    tracker = PerformanceTracker()
    manager = RoleManager(mesh_node, tracker, auto_switch)
    await manager.start()
    return manager
  
