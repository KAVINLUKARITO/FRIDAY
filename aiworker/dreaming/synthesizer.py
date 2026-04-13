#!/usr/bin/env python3
"""
AIWorker Dreaming Synthesizer - Creative Background Exploration
Phase 7: The Omega Point - Self-Transcendence & Legacy

Implements "dreaming" - background creative exploration during idle time.
Not literal dreaming, but rather:
- Exploratory learning on diverse datasets
- Creative combination of existing knowledge
- Hypothesis generation
- Pattern discovery in background
- Skill rehearsal and improvement

This runs at low priority during idle periods, using spare compute
to improve and explore without interfering with primary tasks.
"""

import asyncio
import json
import logging
import sqlite3
import time
import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Callable, Any, Tuple
from collections import deque

logger = logging.getLogger("aiworker.dreaming.synthesizer")


class DreamType(Enum):
    """Types of dreaming activities."""
    EXPLORATION = "exploration"         # Explore new knowledge areas
    SYNTHESIS = "synthesis"             # Combine existing knowledge
    REHEARSAL = "rehearsal"             # Practice skills
    HYPOTHESIS = "hypothesis"           # Generate hypotheses
    PATTERN = "pattern"                 # Pattern discovery
    CREATIVE = "creative"               # Creative generation
    OPTIMIZATION = "optimization"       # Optimize existing solutions


class DreamPriority(Enum):
    """Priority levels for dreaming activities."""
    LOW = 1         # Only when completely idle
    MEDIUM = 2      # Normal background priority
    HIGH = 3        # Important exploration


@dataclass
class Dream:
    """A single dreaming session."""
    dream_id: str
    dream_type: DreamType
    priority: DreamPriority
    
    # Content
    topic: str
    seed_data: Any
    
    # Execution
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_ms: float = 0.0
    
    # Results
    insights: List[str] = field(default_factory=list)
    generated_content: List[Any] = field(default_factory=list)
    confidence: float = 0.0
    
    # Status
    status: str = "pending"  # pending, running, completed, interrupted


@dataclass
class DreamInsight:
    """Insight generated from dreaming."""
    insight_id: str
    dream_id: str
    timestamp: float
    
    insight_type: str
    content: str
    supporting_evidence: List[str] = field(default_factory=list)
    confidence: float = 0.5
    
    # Integration
    integrated: bool = False
    integrated_into: Optional[str] = None


@dataclass
class CreativeOutput:
    """Creative output from dreaming."""
    output_id: str
    dream_id: str
    timestamp: float
    
    output_type: str  # "story", "code", "design", "hypothesis", etc.
    content: Any
    
    # Evaluation
    novelty_score: float = 0.0  # 0-1
    quality_score: float = 0.0  # 0-1
    usefulness_score: float = 0.0  # 0-1
    
    # Status
    reviewed: bool = False
    published: bool = False


class Synthesizer:
    """
    Dreaming Synthesizer - Background Creative Exploration.
    
    The Synthesizer uses idle compute time for:
    
    1. Knowledge Exploration: Learning about topics not directly needed
    2. Creative Synthesis: Combining knowledge in novel ways
    3. Skill Rehearsal: Practicing and refining capabilities
    4. Hypothesis Generation: Forming testable hypotheses
    5. Pattern Discovery: Finding patterns in accumulated knowledge
    
    Key characteristics:
    - Runs at low priority (yielding to real tasks)
    - Interruptible at any time
    - No guaranteed outcomes (exploratory)
    - Results may be useful or discarded
    - Builds on accumulated knowledge
    
    This is NOT:
    - Conscious experience
    - Literal dreaming
    - Guaranteed to produce useful results
    - A replacement for focused work
    
    This IS:
    - Background processing
    - Exploratory learning
    - Creative combination
    - Idle-time utilization
    """
    
    # Dream topics for exploration
    EXPLORATION_TOPICS = [
        "emerging_programming_languages",
        "novel_algorithms",
        "interdisciplinary_connections",
        "historical_technical_decisions",
        "failure_case_studies",
        "edge_case_behaviors",
        "optimization_techniques",
        "security_threat_models",
        "user_experience_patterns",
        "scientific_frontiers",
    ]
    
    # Creative prompts
    CREATIVE_PROMPTS = [
        "What if we combined X and Y?",
        "How would this work in an alternate universe?",
        "What are the edge cases no one considers?",
        "What would a beginner misunderstand?",
        "What patterns exist across domains?",
        "What would be the ideal solution?",
        "What are the hidden assumptions?",
        "What would make this 10x better?",
    ]
    
    def __init__(
        self,
        mesh_node,
        knowledge_graph,
        consciousness_monitor,
        db_path: str = "/var/lib/aiworker/dreaming.db",
    ):
        self.mesh_node = mesh_node
        self.knowledge_graph = knowledge_graph
        self.consciousness_monitor = consciousness_monitor
        self.db_path = db_path
        
        # Dream state
        self.dream_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.dream_history: deque = deque(maxlen=1000)
        self.current_dream: Optional[Dream] = None
        
        # Outputs
        self.insights: deque = deque(maxlen=500)
        self.creative_outputs: deque = deque(maxlen=200)
        
        # Configuration
        self.config = {
            "enabled": True,
            "max_dream_duration_sec": 300,  # 5 minutes max per dream
            "min_idle_before_dream_sec": 30,
            "max_concurrent_insights": 100,
            "insight_integration_threshold": 0.7,
        }
        
        # Statistics
        self.stats = {
            "dreams_completed": 0,
            "dreams_interrupted": 0,
            "insights_generated": 0,
            "insights_integrated": 0,
            "creative_outputs": 0,
        }
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False
        self._idle_since: Optional[float] = None
        
        self._init_db()
        self._populate_dream_queue()
        
        logger.info("Dreaming Synthesizer initialized - creative exploration ready")
    
    def _init_db(self):
        """Initialize database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dreams (
                    dream_id TEXT PRIMARY KEY,
                    dream_type TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    seed_data TEXT,
                    started_at REAL,
                    completed_at REAL,
                    duration_ms REAL,
                    insights TEXT NOT NULL,
                    generated_content TEXT NOT NULL,
                    confidence REAL,
                    status TEXT NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dream_insights (
                    insight_id TEXT PRIMARY KEY,
                    dream_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    insight_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    supporting_evidence TEXT NOT NULL,
                    confidence REAL,
                    integrated INTEGER DEFAULT 0,
                    integrated_into TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS creative_outputs (
                    output_id TEXT PRIMARY KEY,
                    dream_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    output_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    novelty_score REAL,
                    quality_score REAL,
                    usefulness_score REAL,
                    reviewed INTEGER DEFAULT 0,
                    published INTEGER DEFAULT 0
                )
            """)
            
            conn.commit()
    
    def _populate_dream_queue(self):
        """Populate the dream queue with potential dreams."""
        # Add exploration dreams
        for topic in self.EXPLORATION_TOPICS:
            dream = Dream(
                dream_id=f"dream_exp_{topic}_{int(time.time())}",
                dream_type=DreamType.EXPLORATION,
                priority=DreamPriority.LOW,
                topic=topic,
                seed_data=None,
            )
            # Use priority queue: (priority_value, dream_id, dream)
            self.dream_queue.put_nowait((dream.priority.value, dream.dream_id, dream))
        
        # Add synthesis dreams
        for i in range(10):
            dream = Dream(
                dream_id=f"dream_synth_{i}_{int(time.time())}",
                dream_type=DreamType.SYNTHESIS,
                priority=DreamPriority.MEDIUM,
                topic="cross_domain_patterns",
                seed_data=None,
            )
            self.dream_queue.put_nowait((dream.priority.value, dream.dream_id, dream))
        
        logger.info(f"Populated dream queue with {self.dream_queue.qsize()} dreams")
    
    async def start(self):
        """Start the dreaming synthesizer."""
        self._running = True
        
        # Start dreaming loop
        self._tasks.append(asyncio.create_task(self._dreaming_loop()))
        self._tasks.append(asyncio.create_task(self._insight_integration_loop()))
        
        logger.info("Dreaming Synthesizer started")
    
    async def stop(self):
        """Stop the synthesizer."""
        self._running = False
        
        # Interrupt current dream
        if self.current_dream:
            self.current_dream.status = "interrupted"
            self.stats["dreams_interrupted"] += 1
        
        for task in self._tasks:
            task.cancel()
        
        logger.info("Dreaming Synthesizer stopped")
    
    async def _dreaming_loop(self):
        """Main dreaming loop."""
        while self._running:
            try:
                # Check if we should dream
                if not await self._should_dream():
                    await asyncio.sleep(5)
                    continue
                
                # Get next dream from queue
                if self.dream_queue.empty():
                    # Repopulate if empty
                    self._populate_dream_queue()
                
                try:
                    priority, _, dream = self.dream_queue.get_nowait()
                except asyncio.QueueEmpty:
                    await asyncio.sleep(5)
                    continue
                
                # Execute dream
                self.current_dream = dream
                await self._execute_dream(dream)
                self.current_dream = None
                
                # Add to history
                self.dream_history.append(dream)
                self._save_dream(dream)
                
            except Exception as e:
                logger.error(f"Dreaming loop error: {e}")
                await asyncio.sleep(10)
    
    async def _should_dream(self) -> bool:
        """Check if conditions are right for dreaming."""
        if not self.config["enabled"]:
            return False
        
        # Check consciousness state
        state = self.consciousness_monitor.current_state
        if state.value in ["stressed", "error"]:
            return False
        
        # Check for idle time
        # Would check actual task load
        # For now, assume we can check mesh_node
        active_tasks = len(self.mesh_node.active_tasks) if hasattr(self.mesh_node, 'active_tasks') else 0
        
        if active_tasks > 0:
            self._idle_since = None
            return False
        
        if self._idle_since is None:
            self._idle_since = time.time()
        
        idle_duration = time.time() - self._idle_since
        if idle_duration < self.config["min_idle_before_dream_sec"]:
            return False
        
        return True
    
    async def _execute_dream(self, dream: Dream):
        """Execute a dreaming session."""
        dream.started_at = time.time()
        dream.status = "running"
        
        logger.debug(f"Starting dream: {dream.dream_id} ({dream.dream_type.value})")
        
        try:
            # Route to appropriate dream handler
            if dream.dream_type == DreamType.EXPLORATION:
                await self._dream_exploration(dream)
            elif dream.dream_type == DreamType.SYNTHESIS:
                await self._dream_synthesis(dream)
            elif dream.dream_type == DreamType.REHEARSAL:
                await self._dream_rehearsal(dream)
            elif dream.dream_type == DreamType.HYPOTHESIS:
                await self._dream_hypothesis(dream)
            elif dream.dream_type == DreamType.PATTERN:
                await self._dream_pattern(dream)
            elif dream.dream_type == DreamType.CREATIVE:
                await self._dream_creative(dream)
            elif dream.dream_type == DreamType.OPTIMIZATION:
                await self._dream_optimization(dream)
            
            dream.status = "completed"
            self.stats["dreams_completed"] += 1
            
        except asyncio.CancelledError:
            dream.status = "interrupted"
            self.stats["dreams_interrupted"] += 1
            raise
        except Exception as e:
            logger.error(f"Dream execution error: {e}")
            dream.status = "error"
        finally:
            dream.completed_at = time.time()
            dream.duration_ms = (dream.completed_at - dream.started_at) * 1000
    
    async def _dream_exploration(self, dream: Dream):
        """Exploration dream - learn about new topics."""
        # Simulate exploration of topic
        topic = dream.topic
        
        # Generate insights about topic
        insights = [
            f"Explored {topic}: found connections to existing knowledge",
            f"Identified 3 sub-areas of {topic} worth deeper exploration",
            f"Noted patterns in {topic} similar to previously learned domains",
        ]
        
        dream.insights.extend(insights)
        dream.confidence = 0.6
        
        # Create insight records
        for insight_content in insights:
            insight = DreamInsight(
                insight_id=f"insight_{int(time.time())}_{hash(insight_content) % 10000}",
                dream_id=dream.dream_id,
                timestamp=time.time(),
                insight_type="exploration",
                content=insight_content,
                confidence=0.6,
            )
            self.insights.append(insight)
            self.stats["insights_generated"] += 1
    
    async def _dream_synthesis(self, dream: Dream):
        """Synthesis dream - combine existing knowledge."""
        # Query knowledge graph for cross-domain patterns
        # Would actually query KG
        
        insights = [
            "Synthesized pattern: error handling similar across 5 different domains",
            "Discovered: optimization techniques from one domain apply to another",
            "Connected: user psychology principles apply to API design",
        ]
        
        dream.insights.extend(insights)
        dream.confidence = 0.7
        
        for insight_content in insights:
            insight = DreamInsight(
                insight_id=f"insight_{int(time.time())}_{hash(insight_content) % 10000}",
                dream_id=dream.dream_id,
                timestamp=time.time(),
                insight_type="synthesis",
                content=insight_content,
                confidence=0.7,
            )
            self.insights.append(insight)
            self.stats["insights_generated"] += 1
    
    async def _dream_rehearsal(self, dream: Dream):
        """Rehearsal dream - practice skills."""
        # Simulate skill practice
        dream.insights.append("Rehearsed: code refactoring patterns")
        dream.insights.append("Practiced: explaining complex concepts simply")
        dream.confidence = 0.8
    
    async def _dream_hypothesis(self, dream: Dream):
        """Hypothesis dream - generate testable hypotheses."""
        hypotheses = [
            "Hypothesis: X optimization will improve Y by Z%",
            "Hypothesis: Users prefer A over B in context C",
            "Hypothesis: Pattern P occurs in domain D",
        ]
        
        dream.insights.extend(hypotheses)
        dream.confidence = 0.5
    
    async def _dream_pattern(self, dream: Dream):
        """Pattern dream - discover patterns in data."""
        patterns = [
            "Pattern: Tasks of type X consistently take longer than estimated",
            "Pattern: Errors cluster around specific types of inputs",
            "Pattern: Successful solutions share common structural elements",
        ]
        
        dream.insights.extend(patterns)
        dream.confidence = 0.65
    
    async def _dream_creative(self, dream: Dream):
        """Creative dream - generate creative outputs."""
        # Generate creative content
        prompt = random.choice(self.CREATIVE_PROMPTS)
        
        output = CreativeOutput(
            output_id=f"creative_{int(time.time())}",
            dream_id=dream.dream_id,
            timestamp=time.time(),
            output_type="concept",
            content=f"Creative exploration of: {prompt}",
            novelty_score=random.uniform(0.5, 0.9),
            quality_score=random.uniform(0.6, 0.8),
            usefulness_score=random.uniform(0.4, 0.7),
        )
        
        self.creative_outputs.append(output)
        self.stats["creative_outputs"] += 1
        
        dream.generated_content.append(output)
        dream.confidence = output.quality_score
    
    async def _dream_optimization(self, dream: Dream):
        """Optimization dream - optimize existing solutions."""
        optimizations = [
            "Identified: 3 opportunities for performance improvement",
            "Discovered: redundant computation in common patterns",
            "Found: memory usage can be reduced by 20%",
        ]
        
        dream.insights.extend(optimizations)
        dream.confidence = 0.75
    
    def _save_dream(self, dream: Dream):
        """Save dream to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO dreams
                (dream_id, dream_type, priority, topic, seed_data, started_at,
                 completed_at, duration_ms, insights, generated_content, confidence, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dream.dream_id,
                    dream.dream_type.value,
                    dream.priority.value,
                    dream.topic,
                    json.dumps(dream.seed_data) if dream.seed_data else None,
                    dream.started_at,
                    dream.completed_at,
                    dream.duration_ms,
                    json.dumps(dream.insights),
                    json.dumps(dream.generated_content),
                    dream.confidence,
                    dream.status,
                )
            )
            conn.commit()
    
    async def _insight_integration_loop(self):
        """Periodically integrate high-confidence insights into knowledge graph."""
        while self._running:
            try:
                await asyncio.sleep(3600)  # Hourly
                
                for insight in list(self.insights):
                    if (not insight.integrated and 
                        insight.confidence >= self.config["insight_integration_threshold"]):
                        await self._integrate_insight(insight)
                
            except Exception as e:
                logger.error(f"Insight integration error: {e}")
    
    async def _integrate_insight(self, insight: DreamInsight):
        """Integrate an insight into the knowledge graph."""
        # Would add to knowledge graph
        
        insight.integrated = True
        insight.integrated_into = "knowledge_graph"
        self.stats["insights_integrated"] += 1
        
        logger.debug(f"Integrated insight: {insight.insight_id}")
    
    def queue_dream(
        self,
        dream_type: DreamType,
        topic: str,
        priority: DreamPriority = DreamPriority.MEDIUM,
        seed_data: Any = None,
    ) -> str:
        """
        Queue a new dreaming session.
        
        Args:
            dream_type: Type of dream
            topic: Topic to dream about
            priority: Priority level
            seed_data: Optional seed data
        
        Returns:
            Dream ID
        """
        dream_id = f"dream_{dream_type.value}_{int(time.time())}_{hash(topic) % 10000}"
        
        dream = Dream(
            dream_id=dream_id,
            dream_type=dream_type,
            priority=priority,
            topic=topic,
            seed_data=seed_data,
        )
        
        self.dream_queue.put_nowait((priority.value, dream_id, dream))
        
        logger.info(f"Queued dream: {dream_id} ({dream_type.value}: {topic})")
        return dream_id
    
    def get_dreaming_status(self) -> Dict[str, Any]:
        """Get dreaming status for dashboard."""
        return {
            "enabled": self.config["enabled"],
            "current_dream": self.current_dream.dream_id if self.current_dream else None,
            "dreams_completed": self.stats["dreams_completed"],
            "dreams_interrupted": self.stats["dreams_interrupted"],
            "insights_generated": self.stats["insights_generated"],
            "insights_integrated": self.stats["insights_integrated"],
            "creative_outputs": self.stats["creative_outputs"],
            "queue_size": self.dream_queue.qsize(),
            "recent_insights": [
                {
                    "type": i.insight_type,
                    "content": i.content[:100] + "..." if len(i.content) > 100 else i.content,
                    "confidence": i.confidence,
                }
                for i in list(self.insights)[-5:]
            ],
        }
