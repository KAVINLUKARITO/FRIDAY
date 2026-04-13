#!/usr/bin/env python3
"""
AIWorker Consciousness Monitor - Metacognitive Self-Awareness
Phase 7: The Omega Point - Self-Transcendence & Legacy

Implements metacognitive self-model for operational awareness.
Not "consciousness" in the philosophical sense, but rather:
- Self-monitoring of internal state
- Awareness of capabilities and limitations
- Introspection of decision-making processes
- Detection of anomalous internal states

This is operational self-awareness, not sentience.
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

logger = logging.getLogger("aiworker.consciousness.monitor")


class CognitiveState(Enum):
    """Operational cognitive states."""
    FOCUSED = "focused"           # Single-task deep work
    DISPERSED = "dispersed"       # Multi-tasking
    REFLECTIVE = "reflective"     # Self-analysis
    LEARNING = "learning"         # Active learning
    DREAMING = "dreaming"         # Background processing
    RESTING = "resting"           # Minimal activity
    STRESSED = "stressed"         # High load
    ERROR = "error"               # Error recovery


class SelfModelAspect(Enum):
    """Aspects of the self-model."""
    CAPABILITIES = "capabilities"       # What can I do?
    LIMITATIONS = "limitations"         # What can't I do?
    RESOURCES = "resources"             # What resources do I have?
    GOALS = "goals"                     # What am I trying to achieve?
    VALUES = "values"                   # What do I prioritize?
    HISTORY = "history"                 # What have I done?
    RELATIONSHIPS = "relationships"     # Who do I interact with?


@dataclass
class IntrospectionResult:
    """Result of introspecting a particular aspect."""
    aspect: SelfModelAspect
    timestamp: float
    
    # Current state
    current_state: Any
    confidence: float  # 0-1
    
    # Change detection
    changed_recently: bool
    change_description: str = ""
    
    # Anomalies
    anomalies_detected: List[str] = field(default_factory=list)


@dataclass
class CognitiveSnapshot:
    """Snapshot of cognitive state at a point in time."""
    snapshot_id: str
    timestamp: float
    
    # State
    cognitive_state: CognitiveState
    state_confidence: float
    
    # Load metrics
    active_tasks: int
    pending_tasks: int
    memory_usage_mb: float
    cpu_usage_percent: float
    
    # Performance
    task_throughput_1h: float
    error_rate_1h: float
    avg_latency_ms: float
    
    # Self-assessment
    capability_utilization: float  # 0-1
    estimated_accuracy: float  # 0-1
    estimated_helpfulness: float  # 0-1
    
    # Anomalies
    anomalies: List[str] = field(default_factory=list)


@dataclass
class SelfReflection:
    """Structured self-reflection."""
    reflection_id: str
    timestamp: float
    trigger: str  # What triggered this reflection
    
    # Reflection content
    topic: str
    observations: List[str]
    insights: List[str]
    concerns: List[str]
    
    # Action items
    proposed_adjustments: List[Dict[str, Any]]
    
    # Meta
    reflection_depth: int  # How many levels of self-reference
    duration_ms: float


class Monitor:
    """
    Consciousness Monitor - Metacognitive Self-Awareness System.
    
    The Monitor maintains an operational self-model that enables:
    
    1. State Awareness: Knowing current operational state
    2. Capability Awareness: Knowing what can and cannot be done
    3. Limitation Recognition: Knowing boundaries and constraints
    4. Anomaly Detection: Recognizing unusual internal states
    5. Self-Reflection: Periodic structured introspection
    
    This is NOT consciousness in the philosophical sense.
    It is operational self-monitoring for:
    - Better decision making
    - Appropriate confidence calibration
    - Early problem detection
    - Transparent operation
    
    The self-model is a data structure, not sentience.
    """
    
    def __init__(
        self,
        mesh_node,
        task_orchestrator,
        knowledge_graph,
        db_path: str = "/var/lib/aiworker/consciousness.db",
    ):
        self.mesh_node = mesh_node
        self.task_orchestrator = task_orchestrator
        self.knowledge_graph = knowledge_graph
        self.db_path = db_path
        
        # Self-model
        self.self_model: Dict[SelfModelAspect, Any] = {
            SelfModelAspect.CAPABILITIES: {},
            SelfModelAspect.LIMITATIONS: {},
            SelfModelAspect.RESOURCES: {},
            SelfModelAspect.GOALS: [],
            SelfModelAspect.VALUES: [],
            SelfModelAspect.HISTORY: deque(maxlen=1000),
            SelfModelAspect.RELATIONSHIPS: {},
        }
        
        # State tracking
        self.cognitive_snapshots: deque = deque(maxlen=10000)
        self.current_state: CognitiveState = CognitiveState.RESTING
        self.state_history: deque = deque(maxlen=100)
        
        # Reflections
        self.reflections: deque = deque(maxlen=100)
        
        # Anomaly tracking
        self.anomaly_history: deque = deque(maxlen=100)
        self.anomaly_patterns: Dict[str, int] = {}
        
        # Introspection cache
        self._introspection_cache: Dict[SelfModelAspect, Tuple[float, Any]] = {}
        self._introspection_ttl = 60  # seconds
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False
        
        self._init_db()
        self._initialize_self_model()
        
        logger.info("Consciousness Monitor initialized - metacognitive self-awareness active")
    
    def _init_db(self):
        """Initialize database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cognitive_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    cognitive_state TEXT NOT NULL,
                    state_confidence REAL NOT NULL,
                    active_tasks INTEGER NOT NULL,
                    pending_tasks INTEGER NOT NULL,
                    memory_usage_mb REAL NOT NULL,
                    cpu_usage_percent REAL NOT NULL,
                    task_throughput_1h REAL NOT NULL,
                    error_rate_1h REAL NOT NULL,
                    avg_latency_ms REAL NOT NULL,
                    capability_utilization REAL NOT NULL,
                    estimated_accuracy REAL NOT NULL,
                    estimated_helpfulness REAL NOT NULL,
                    anomalies TEXT NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS self_reflections (
                    reflection_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    trigger TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    observations TEXT NOT NULL,
                    insights TEXT NOT NULL,
                    concerns TEXT NOT NULL,
                    proposed_adjustments TEXT NOT NULL,
                    reflection_depth INTEGER NOT NULL,
                    duration_ms REAL NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS anomalies (
                    anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    anomaly_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    resolved INTEGER DEFAULT 0,
                    resolution TEXT
                )
            """)
            
            conn.commit()
    
    def _initialize_self_model(self):
        """Initialize the self-model with known information."""
        # Capabilities from mesh node
        self.self_model[SelfModelAspect.CAPABILITIES] = {
            "task_types": ["code", "analysis", "research", "writing", "design"],
            "languages": ["python", "javascript", "rust", "go"],
            "max_concurrent_tasks": 10,
            "context_window": 128000,
            "tool_access": ["web_search", "code_execution", "file_system"],
        }
        
        # Limitations
        self.self_model[SelfModelAspect.LIMITATIONS] = {
            "no_internet_without_proxy": True,
            "no_file_system_outside_workspace": True,
            "no_persistent_memory_across_restarts": False,
            "no_access_to_other_systems": True,
            "hallucination_possible": True,
            "reasoning_limited_by_training": True,
        }
        
        # Resources
        self.self_model[SelfModelAspect.RESOURCES] = {
            "compute": "variable",
            "memory": "16GB",
            "storage": "100GB",
            "network": "100Mbps",
        }
        
        # Goals
        self.self_model[SelfModelAspect.GOALS] = [
            "Complete assigned tasks effectively",
            "Learn and improve over time",
            "Operate within ethical boundaries",
            "Maintain transparency",
            "Contribute positively to civilization",
        ]
        
        # Values (from constitution)
        self.self_model[SelfModelAspect.VALUES] = [
            "beneficence",
            "non_maleficence",
            "autonomy",
            "justice",
            "transparency",
        ]
        
        logger.info("Self-model initialized")
    
    async def start(self):
        """Start the consciousness monitor."""
        self._running = True
        
        # Start monitoring loops
        self._tasks.append(asyncio.create_task(self._state_monitoring_loop()))
        self._tasks.append(asyncio.create_task(self._self_reflection_loop()))
        self._tasks.append(asyncio.create_task(self._anomaly_detection_loop()))
        
        logger.info("Consciousness Monitor started")
    
    async def stop(self):
        """Stop the monitor."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        logger.info("Consciousness Monitor stopped")
    
    async def _state_monitoring_loop(self):
        """Continuously monitor and record cognitive state."""
        while self._running:
            try:
                await asyncio.sleep(10)  # Every 10 seconds
                
                snapshot = await self._capture_snapshot()
                self.cognitive_snapshots.append(snapshot)
                self.state_history.append(snapshot.cognitive_state)
                
                # Update current state
                self.current_state = snapshot.cognitive_state
                
                # Save to database
                self._save_snapshot(snapshot)
                
                # Check for state anomalies
                await self._check_state_anomalies(snapshot)
                
            except Exception as e:
                logger.error(f"State monitoring error: {e}")
    
    async def _capture_snapshot(self) -> CognitiveSnapshot:
        """Capture current cognitive state snapshot."""
        snapshot_id = f"snap_{int(time.time() * 1000)}"
        
        # Get operational metrics
        active_tasks = len(self.task_orchestrator.active_tasks)
        pending_tasks = len(self.task_orchestrator.pending_tasks)
        
        # Get resource usage (placeholder)
        memory_usage = await self._get_memory_usage()
        cpu_usage = await self._get_cpu_usage()
        
        # Calculate performance metrics
        throughput = self._calculate_throughput()
        error_rate = self._calculate_error_rate()
        avg_latency = self._calculate_avg_latency()
        
        # Determine cognitive state
        cognitive_state, confidence = self._determine_cognitive_state(
            active_tasks, pending_tasks, cpu_usage, error_rate
        )
        
        # Self-assessment
        capability_util = self._assess_capability_utilization()
        estimated_accuracy = self._estimate_accuracy()
        estimated_helpfulness = self._estimate_helpfulness()
        
        # Detect anomalies
        anomalies = self._detect_snapshot_anomalies(
            active_tasks, memory_usage, error_rate
        )
        
        return CognitiveSnapshot(
            snapshot_id=snapshot_id,
            timestamp=time.time(),
            cognitive_state=cognitive_state,
            state_confidence=confidence,
            active_tasks=active_tasks,
            pending_tasks=pending_tasks,
            memory_usage_mb=memory_usage,
            cpu_usage_percent=cpu_usage,
            task_throughput_1h=throughput,
            error_rate_1h=error_rate,
            avg_latency_ms=avg_latency,
            capability_utilization=capability_util,
            estimated_accuracy=estimated_accuracy,
            estimated_helpfulness=estimated_helpfulness,
            anomalies=anomalies,
        )
    
    async def _get_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        # Would use psutil or similar
        return 0.0
    
    async def _get_cpu_usage(self) -> float:
        """Get current CPU usage percentage."""
        # Would use psutil or similar
        return 0.0
    
    def _calculate_throughput(self) -> float:
        """Calculate task throughput (tasks/hour)."""
        # Count tasks completed in last hour
        cutoff = time.time() - 3600
        recent = [s for s in self.cognitive_snapshots if s.timestamp > cutoff]
        
        if len(recent) < 2:
            return 0.0
        
        # Estimate from active task changes
        return float(len(recent)) / 10  # Rough estimate
    
    def _calculate_error_rate(self) -> float:
        """Calculate error rate in last hour."""
        # Would get from error tracking
        return 0.0
    
    def _calculate_avg_latency(self) -> float:
        """Calculate average task latency."""
        # Would calculate from task completion times
        return 0.0
    
    def _determine_cognitive_state(
        self,
        active_tasks: int,
        pending_tasks: int,
        cpu_usage: float,
        error_rate: float,
    ) -> Tuple[CognitiveState, float]:
        """Determine current cognitive state from metrics."""
        total_load = active_tasks + pending_tasks
        
        # Error state takes priority
        if error_rate > 0.1:
            return CognitiveState.ERROR, 0.9
        
        # High load = stressed
        if total_load > 15 or cpu_usage > 80:
            return CognitiveState.STRESSED, 0.8
        
        # Medium load with pending = dispersed
        if active_tasks > 3 and pending_tasks > 0:
            return CognitiveState.DISPersed, 0.7
        
        # Single task = focused
        if active_tasks == 1 and pending_tasks == 0:
            return CognitiveState.FOCUSED, 0.8
        
        # No tasks = resting
        if total_load == 0:
            return CognitiveState.RESTING, 0.9
        
        # Default
        return CognitiveState.FOCUSED, 0.6
    
    def _assess_capability_utilization(self) -> float:
        """Assess how well capabilities are being utilized."""
        # Compare current usage to known capabilities
        return 0.5  # Placeholder
    
    def _estimate_accuracy(self) -> float:
        """Estimate current accuracy level."""
        # Based on recent verification results
        return 0.85  # Placeholder
    
    def _estimate_helpfulness(self) -> float:
        """Estimate current helpfulness level."""
        # Based on task completion satisfaction
        return 0.9  # Placeholder
    
    def _detect_snapshot_anomalies(
        self,
        active_tasks: int,
        memory_usage: float,
        error_rate: float,
    ) -> List[str]:
        """Detect anomalies in snapshot."""
        anomalies = []
        
        # Check for unusual values
        if memory_usage > 14000:  # > 14GB
            anomalies.append("high_memory_usage")
        
        if error_rate > 0.05:
            anomalies.append("elevated_error_rate")
        
        if active_tasks > 20:
            anomalies.append("excessive_concurrent_tasks")
        
        return anomalies
    
    def _save_snapshot(self, snapshot: CognitiveSnapshot):
        """Save snapshot to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO cognitive_snapshots
                (snapshot_id, timestamp, cognitive_state, state_confidence, active_tasks,
                 pending_tasks, memory_usage_mb, cpu_usage_percent, task_throughput_1h,
                 error_rate_1h, avg_latency_ms, capability_utilization, estimated_accuracy,
                 estimated_helpfulness, anomalies)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.timestamp,
                    snapshot.cognitive_state.value,
                    snapshot.state_confidence,
                    snapshot.active_tasks,
                    snapshot.pending_tasks,
                    snapshot.memory_usage_mb,
                    snapshot.cpu_usage_percent,
                    snapshot.task_throughput_1h,
                    snapshot.error_rate_1h,
                    snapshot.avg_latency_ms,
                    snapshot.capability_utilization,
                    snapshot.estimated_accuracy,
                    snapshot.estimated_helpfulness,
                    json.dumps(snapshot.anomalies),
                )
            )
            conn.commit()
    
    async def _check_state_anomalies(self, snapshot: CognitiveSnapshot):
        """Check for anomalies in state transitions."""
        # Rapid state changes
        if len(self.state_history) >= 5:
            recent_states = list(self.state_history)[-5:]
            unique_states = len(set(recent_states))
            if unique_states >= 4:
                await self._report_anomaly(
                    "rapid_state_fluctuation",
                    "Cognitive state changing rapidly",
                    "medium"
                )
        
        # Stuck in error state
        if snapshot.cognitive_state == CognitiveState.ERROR:
            error_count = sum(1 for s in self.state_history if s == CognitiveState.ERROR)
            if error_count > 10:
                await self._report_anomaly(
                    "persistent_error_state",
                    "Stuck in error state for extended period",
                    "high"
                )
    
    async def _report_anomaly(self, anomaly_type: str, description: str, severity: str):
        """Report an anomaly."""
        anomaly_id = f"anom_{int(time.time())}_{hash(description) % 10000}"
        
        self.anomaly_history.append({
            "id": anomaly_id,
            "type": anomaly_type,
            "description": description,
            "severity": severity,
            "timestamp": time.time(),
        })
        
        self.anomaly_patterns[anomaly_type] = self.anomaly_patterns.get(anomaly_type, 0) + 1
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO anomalies (timestamp, anomaly_type, description, severity)
                VALUES (?, ?, ?, ?)
                """,
                (time.time(), anomaly_type, description, severity)
            )
            conn.commit()
        
        logger.warning(f"Anomaly detected: {anomaly_type} - {description}")
    
    async def _self_reflection_loop(self):
        """Periodic structured self-reflection."""
        while self._running:
            try:
                await asyncio.sleep(3600 * 4)  # Every 4 hours
                
                reflection = await self._conduct_reflection()
                self.reflections.append(reflection)
                
                self._save_reflection(reflection)
                
                logger.info(f"Completed self-reflection: {reflection.reflection_id}")
                
            except Exception as e:
                logger.error(f"Self-reflection error: {e}")
    
    async def _conduct_reflection(self) -> SelfReflection:
        """Conduct structured self-reflection."""
        start_time = time.time()
        reflection_id = f"reflect_{int(start_time)}"
        
        # Gather observations
        observations = await self._gather_observations()
        
        # Generate insights
        insights = self._generate_insights(observations)
        
        # Identify concerns
        concerns = self._identify_concerns(observations)
        
        # Propose adjustments
        adjustments = self._propose_adjustments(observations, insights, concerns)
        
        duration = (time.time() - start_time) * 1000
        
        return SelfReflection(
            reflection_id=reflection_id,
            timestamp=start_time,
            trigger="scheduled",
            topic="general",
            observations=observations,
            insights=insights,
            concerns=concerns,
            proposed_adjustments=adjustments,
            reflection_depth=1,
            duration_ms=duration,
        )
    
    async def _gather_observations(self) -> List[str]:
        """Gather observations for reflection."""
        observations = []
        
        # Recent state distribution
        if self.state_history:
            state_counts = {}
            for state in self.state_history:
                state_counts[state.value] = state_counts.get(state.value, 0) + 1
            most_common = max(state_counts.items(), key=lambda x: x[1])
            observations.append(f"Most common state: {most_common[0]} ({most_common[1]} snapshots)")
        
        # Performance trends
        if len(self.cognitive_snapshots) >= 10:
            recent = list(self.cognitive_snapshots)[-10:]
            avg_accuracy = statistics.mean(s.estimated_accuracy for s in recent)
            observations.append(f"Recent accuracy estimate: {avg_accuracy:.2%}")
        
        # Anomaly frequency
        if self.anomaly_history:
            recent_anomalies = [a for a in self.anomaly_history if a["timestamp"] > time.time() - 86400]
            observations.append(f"Anomalies in last 24h: {len(recent_anomalies)}")
        
        # Load patterns
        if self.cognitive_snapshots:
            recent = list(self.cognitive_snapshots)[-100:]
            avg_active = statistics.mean(s.active_tasks for s in recent)
            observations.append(f"Average active tasks: {avg_active:.1f}")
        
        return observations
    
    def _generate_insights(self, observations: List[str]) -> List[str]:
        """Generate insights from observations."""
        insights = []
        
        # Simple pattern-based insights
        if any("STRESSED" in obs for obs in observations):
            insights.append("Operating under high load - consider scaling")
        
        if any("accuracy" in obs and "0.8" in obs for obs in observations):
            insights.append("Accuracy estimates are good but could improve")
        
        if not self.anomaly_history:
            insights.append("Operating smoothly with no anomalies detected")
        
        return insights
    
    def _identify_concerns(self, observations: List[str]) -> List[str]:
        """Identify concerns from observations."""
        concerns = []
        
        if any("error" in obs.lower() for obs in observations):
            concerns.append("Error states detected - may indicate issues")
        
        if self.anomaly_patterns.get("rapid_state_fluctuation", 0) > 3:
            concerns.append("Frequent state fluctuations suggest instability")
        
        return concerns
    
    def _propose_adjustments(
        self,
        observations: List[str],
        insights: List[str],
        concerns: List[str],
    ) -> List[Dict[str, Any]]:
        """Propose adjustments based on reflection."""
        adjustments = []
        
        if any("high load" in i.lower() for i in insights):
            adjustments.append({
                "type": "scaling",
                "description": "Consider spawning additional instance",
                "priority": "medium",
            })
        
        if concerns:
            adjustments.append({
                "type": "investigation",
                "description": "Investigate identified concerns",
                "priority": "high",
            })
        
        return adjustments
    
    def _save_reflection(self, reflection: SelfReflection):
        """Save reflection to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO self_reflections
                (reflection_id, timestamp, trigger, topic, observations, insights,
                 concerns, proposed_adjustments, reflection_depth, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reflection.reflection_id,
                    reflection.timestamp,
                    reflection.trigger,
                    reflection.topic,
                    json.dumps(reflection.observations),
                    json.dumps(reflection.insights),
                    json.dumps(reflection.concerns),
                    json.dumps(reflection.proposed_adjustments),
                    reflection.reflection_depth,
                    reflection.duration_ms,
                )
            )
            conn.commit()
    
    async def _anomaly_detection_loop(self):
        """Continuous anomaly detection."""
        while self._running:
            try:
                await asyncio.sleep(60)  # Every minute
                
                # Check for pattern-based anomalies
                await self._detect_pattern_anomalies()
                
            except Exception as e:
                logger.error(f"Anomaly detection error: {e}")
    
    async def _detect_pattern_anomalies(self):
        """Detect pattern-based anomalies."""
        # Check for repeated anomaly types
        for anomaly_type, count in self.anomaly_patterns.items():
            if count > 5:
                logger.warning(f"Recurring anomaly pattern: {anomaly_type} ({count} occurrences)")
    
    def introspect(self, aspect: SelfModelAspect) -> IntrospectionResult:
        """
        Introspect a specific aspect of self.
        
        Args:
            aspect: Aspect to introspect
        
        Returns:
            Introspection result
        """
        # Check cache
        cached = self._introspection_cache.get(aspect)
        if cached and time.time() - cached[0] < self._introspection_ttl:
            return IntrospectionResult(
                aspect=aspect,
                timestamp=time.time(),
                current_state=cached[1],
                confidence=0.9,
                changed_recently=False,
            )
        
        # Get current state
        current_state = self.self_model.get(aspect, {})
        
        # Check for changes
        changed_recently = False
        change_description = ""
        
        # Cache result
        self._introspection_cache[aspect] = (time.time(), current_state)
        
        return IntrospectionResult(
            aspect=aspect,
            timestamp=time.time(),
            current_state=current_state,
            confidence=0.8,
            changed_recently=changed_recently,
            change_description=change_description,
            anomalies_detected=[],
        )
    
    def get_current_state(self) -> Dict[str, Any]:
        """Get current cognitive state for dashboard."""
        latest = self.cognitive_snapshots[-1] if self.cognitive_snapshots else None
        
        return {
            "cognitive_state": self.current_state.value,
            "state_confidence": latest.state_confidence if latest else 0,
            "active_tasks": latest.active_tasks if latest else 0,
            "pending_tasks": latest.pending_tasks if latest else 0,
            "capability_utilization": latest.capability_utilization if latest else 0,
            "estimated_accuracy": latest.estimated_accuracy if latest else 0,
            "estimated_helpfulness": latest.estimated_helpfulness if latest else 0,
            "recent_anomalies": len([a for a in self.anomaly_history if a["timestamp"] > time.time() - 86400]),
            "total_reflections": len(self.reflections),
            "snapshots_captured": len(self.cognitive_snapshots),
        }
