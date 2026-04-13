"""
AIWorker Autonomous Goal Generator - Phase 4 Autonomous Intelligence

Generates optimization goals based on system analysis without human prompting.

Input signals:
- Telemetry: Sustained high memory usage → "Optimize memory in X module"
- Test coverage: Low coverage files → "Add tests for Y module"
- Error logs: Recurring exceptions → "Fix error handling in Z"
- Performance: Slow operations → "Optimize hot path in W"
- Code quality: Complexity metrics → "Refactor complex function"
- Research: New best practices → "Apply pattern P to codebase"

Prioritization scoring:
score = (impact * urgency * confidence) / (effort * risk)

Integration:
- SequentialEngine calls generate_goal() when context.goal is empty
- Dashboard shows "Upcoming Goals" queue
- Human can override, reprioritize, or delete generated goals
"""

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from aiworker.config import AIWorkerConfig

logger = logging.getLogger("aiworker.goals")


@dataclass
class AutonomousGoal:
    """An autonomously generated goal."""
    goal_type: str  # "optimize_memory", "improve_coverage", "fix_error_handling", etc.
    description: str
    target_file: Optional[Path]
    rationale: str  # Why this goal now?
    priority_score: float
    expected_outcome: str
    suggested_approach: str
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending, in_progress, completed, rejected
    iteration_id: Optional[str] = None


class GoalGenerator:
    """
    Autonomous goal generation based on system analysis.
    
    Replaces heuristic/round-robin goal selection with data-driven
    generation that responds to actual system needs.
    """
    
    # Goal type templates
    GOAL_TEMPLATES = {
        "optimize_memory": {
            "description": "Optimize memory usage in {target}",
            "rationale": "Telemetry shows sustained high memory usage ({value:.1f}GB peak)",
            "approach": "Identify memory-intensive operations, reduce allocations, add cleanup"
        },
        "improve_coverage": {
            "description": "Add tests for {target}",
            "rationale": "Test coverage is below threshold ({value:.0f}%)",
            "approach": "Identify untested code paths, add unit and integration tests"
        },
        "fix_error_handling": {
            "description": "Improve error handling in {target}",
            "rationale": "Recurring exceptions detected ({value} occurrences)",
            "approach": "Add try-except blocks, improve error messages, add recovery logic"
        },
        "refactor_complexity": {
            "description": "Refactor complex function in {target}",
            "rationale": "High cyclomatic complexity detected ({value})",
            "approach": "Break into smaller functions, simplify control flow"
        },
        "optimize_performance": {
            "description": "Optimize performance in {target}",
            "rationale": "Slow operations detected ({value:.1f}s avg)",
            "approach": "Profile hot paths, optimize algorithms, add caching"
        },
        "apply_pattern": {
            "description": "Apply {pattern} pattern to {target}",
            "rationale": "New best practice identified from research",
            "approach": "Integrate pattern into codebase with proper tests"
        },
        "reduce_latency": {
            "description": "Reduce I/O latency in {target}",
            "rationale": "High I/O wait detected ({value:.0f}%)",
            "approach": "Batch operations, add async, optimize queries"
        }
    }
    
    def __init__(self, config: Optional[AIWorkerConfig] = None):
        self.config = config or AIWorkerConfig.from_env()
        self.base_path = Path(self.config.base_path)
        
        # Thresholds for goal generation
        self.memory_threshold_gb = 25.0
        self.coverage_threshold_percent = 70.0
        self.complexity_threshold = 15
        self.error_frequency_threshold = 3
        
        # Initialize database
        self._init_database()
        
        logger.info("GoalGenerator initialized")
    
    def _init_database(self):
        """Initialize SQLite database for goals."""
        db_path = self.base_path / "data" / "goals.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS autonomous_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                goal_type TEXT NOT NULL,
                description TEXT NOT NULL,
                target_file TEXT,
                rationale TEXT,
                priority_score REAL,
                expected_outcome TEXT,
                suggested_approach TEXT,
                status TEXT DEFAULT 'pending',
                iteration_id TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_goals_status 
            ON autonomous_goals(status)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_goals_priority 
            ON autonomous_goals(priority_score)
        ''')
        
        conn.commit()
        conn.close()
    
    def _get_db_path(self) -> Path:
        """Get database path."""
        return self.base_path / "data" / "goals.db"
    
    def _get_telemetry_data(self, days: int = 1) -> dict:
        """Get recent telemetry data."""
        try:
            cutoff = time.time() - (days * 24 * 3600)
            
            telemetry_db = self.base_path / "data" / "telemetry.db"
            if not telemetry_db.exists():
                return {}
            
            conn = sqlite3.connect(str(telemetry_db))
            cursor = conn.cursor()
            
            # Get latest metrics
            metrics = {}
            
            cursor.execute('''
                SELECT metric_type, AVG(value) as avg, MAX(value) as max
                FROM telemetry_samples
                WHERE timestamp > ?
                GROUP BY metric_type
            ''', (cutoff,))
            
            for row in cursor.fetchall():
                metrics[row[0]] = {'avg': row[1], 'max': row[2]}
            
            conn.close()
            return metrics
        
        except Exception as e:
            logger.debug(f"Failed to get telemetry: {e}")
            return {}
    
    def _get_error_data(self, days: int = 1) -> dict:
        """Get recent error data from logs."""
        errors = {}
        
        try:
            log_file = self.base_path / "logs" / "aiworker.log"
            if not log_file.exists():
                return errors
            
            # Read last 1000 lines
            with open(log_file, 'r') as f:
                lines = f.readlines()[-1000:]
            
            # Count ERROR lines
            for line in lines:
                if 'ERROR' in line:
                    # Extract module/file from line
                    match = re.search(r'aiworker/(\w+)', line)
                    if match:
                        module = match.group(1)
                        errors[module] = errors.get(module, 0) + 1
            
            return errors
        
        except Exception as e:
            logger.debug(f"Failed to get error data: {e}")
            return errors
    
    def _analyze_code_complexity(self) -> list[tuple[Path, int]]:
        """Analyze Python files for complexity."""
        complex_files = []
        
        try:
            aiworker_dir = self.base_path / "aiworker"
            
            for py_file in aiworker_dir.rglob("*.py"):
                try:
                    with open(py_file, 'r') as f:
                        content = f.read()
                    
                    # Simple complexity metric: count of if/for/while/except
                    complexity = len(re.findall(r'\b(if|for|while|except|with)\b', content))
                    
                    if complexity > self.complexity_threshold:
                        complex_files.append((py_file, complexity))
                
                except Exception:
                    continue
            
            # Sort by complexity
            complex_files.sort(key=lambda x: -x[1])
        
        except Exception as e:
            logger.debug(f"Failed to analyze complexity: {e}")
        
        return complex_files[:5]  # Top 5 most complex
    
    def _calculate_priority(
        self,
        impact: float,
        urgency: float,
        confidence: float,
        effort: float,
        risk: float
    ) -> float:
        """
        Calculate priority score.
        
        score = (impact * urgency * confidence) / (effort * risk)
        """
        if effort <= 0 or risk <= 0:
            return 0.0
        
        numerator = impact * urgency * confidence
        denominator = effort * risk
        
        score = numerator / denominator
        
        # Normalize to 0-100 scale
        return min(100.0, score * 10)
    
    def _generate_memory_goal(self, telemetry: dict) -> Optional[AutonomousGoal]:
        """Generate memory optimization goal if needed."""
        memory_data = telemetry.get('memory_used_gb', {})
        peak_memory = memory_data.get('max', 0)
        
        if peak_memory < self.memory_threshold_gb:
            return None
        
        # Find high-memory modules from telemetry
        high_memory_module = "core modules"  # Would need module-level telemetry
        
        impact = min(1.0, peak_memory / 28.0)  # Higher impact near limit
        urgency = 0.9 if peak_memory > 27 else 0.7
        confidence = 0.8
        effort = 0.6
        risk = 0.3
        
        priority = self._calculate_priority(impact, urgency, confidence, effort, risk)
        
        return AutonomousGoal(
            goal_type="optimize_memory",
            description=f"Optimize memory usage in {high_memory_module}",
            target_file=None,
            rationale=f"Telemetry shows sustained high memory usage ({peak_memory:.1f}GB peak)",
            priority_score=priority,
            expected_outcome="15-20% reduction in peak memory usage",
            suggested_approach="Identify memory-intensive operations, reduce allocations, add cleanup"
        )
    
    def _generate_error_handling_goal(self, errors: dict) -> Optional[AutonomousGoal]:
        """Generate error handling improvement goal if needed."""
        if not errors:
            return None
        
        # Find module with most errors
        top_module = max(errors.items(), key=lambda x: x[1])
        module_name, error_count = top_module
        
        if error_count < self.error_frequency_threshold:
            return None
        
        impact = min(1.0, error_count / 10.0)
        urgency = 0.7
        confidence = 0.75
        effort = 0.5
        risk = 0.2
        
        priority = self._calculate_priority(impact, urgency, confidence, effort, risk)
        
        target_file = self.base_path / "aiworker" / module_name / "engine.py"
        
        return AutonomousGoal(
            goal_type="fix_error_handling",
            description=f"Improve error handling in {module_name} module",
            target_file=target_file if target_file.exists() else None,
            rationale=f"Recurring exceptions detected ({error_count} occurrences in {module_name})",
            priority_score=priority,
            expected_outcome="Fewer unhandled exceptions, better error messages",
            suggested_approach="Add try-except blocks, improve error messages, add recovery logic"
        )
    
    def _generate_complexity_goal(self, complex_files: list) -> Optional[AutonomousGoal]:
        """Generate refactoring goal for complex code."""
        if not complex_files:
            return None
        
        top_file, complexity = complex_files[0]
        
        impact = min(1.0, complexity / 30.0)
        urgency = 0.5  # Not urgent, but good for maintainability
        confidence = 0.7
        effort = 0.7
        risk = 0.4
        
        priority = self._calculate_priority(impact, urgency, confidence, effort, risk)
        
        return AutonomousGoal(
            goal_type="refactor_complexity",
            description=f"Refactor complex code in {top_file.name}",
            target_file=top_file,
            rationale=f"High cyclomatic complexity detected ({complexity} branching points)",
            priority_score=priority,
            expected_outcome="More maintainable code, easier testing",
            suggested_approach="Break into smaller functions, simplify control flow"
        )
    
    def generate_goals(self) -> list[AutonomousGoal]:
        """
        Generate autonomous goals based on system analysis.
        
        Returns:
            List of AutonomousGoal objects sorted by priority
        """
        logger.info("Generating autonomous goals")
        
        goals = []
        
        # Gather data
        telemetry = self._get_telemetry_data(days=1)
        errors = self._get_error_data(days=1)
        complex_files = self._analyze_code_complexity()
        
        # Generate goals from each signal
        memory_goal = self._generate_memory_goal(telemetry)
        if memory_goal:
            goals.append(memory_goal)
        
        error_goal = self._generate_error_handling_goal(errors)
        if error_goal:
            goals.append(error_goal)
        
        complexity_goal = self._generate_complexity_goal(complex_files)
        if complexity_goal:
            goals.append(complexity_goal)
        
        # Sort by priority
        goals.sort(key=lambda g: g.priority_score, reverse=True)
        
        # Persist goals
        self._persist_goals(goals)
        
        logger.info(f"Generated {len(goals)} autonomous goals")
        
        return goals
    
    def _persist_goals(self, goals: list[AutonomousGoal]):
        """Persist goals to database."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            for goal in goals:
                # Check if similar goal already exists
                cursor.execute('''
                    SELECT id FROM autonomous_goals
                    WHERE goal_type = ? AND target_file = ? AND status = 'pending'
                ''', (goal.goal_type, str(goal.target_file) if goal.target_file else None))
                
                if cursor.fetchone():
                    continue  # Skip duplicate
                
                cursor.execute('''
                    INSERT INTO autonomous_goals 
                    (created_at, goal_type, description, target_file, rationale,
                     priority_score, expected_outcome, suggested_approach, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    goal.created_at,
                    goal.goal_type,
                    goal.description,
                    str(goal.target_file) if goal.target_file else None,
                    goal.rationale,
                    goal.priority_score,
                    goal.expected_outcome,
                    goal.suggested_approach,
                    goal.status
                ))
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.warning(f"Failed to persist goals: {e}")
    
    def get_next_goal(self) -> Optional[AutonomousGoal]:
        """Get the highest priority pending goal."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM autonomous_goals
                WHERE status = 'pending'
                ORDER BY priority_score DESC
                LIMIT 1
            ''')
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return AutonomousGoal(
                    goal_type=row[2],
                    description=row[3],
                    target_file=Path(row[4]) if row[4] else None,
                    rationale=row[5],
                    priority_score=row[6],
                    expected_outcome=row[7],
                    suggested_approach=row[8],
                    created_at=row[1],
                    status=row[9]
                )
        
        except Exception as e:
            logger.warning(f"Failed to get next goal: {e}")
        
        return None
    
    def get_goal_queue(self, limit: int = 10) -> list[AutonomousGoal]:
        """Get pending goals queue."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM autonomous_goals
                WHERE status = 'pending'
                ORDER BY priority_score DESC
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [
                AutonomousGoal(
                    goal_type=row[2],
                    description=row[3],
                    target_file=Path(row[4]) if row[4] else None,
                    rationale=row[5],
                    priority_score=row[6],
                    expected_outcome=row[7],
                    suggested_approach=row[8],
                    created_at=row[1],
                    status=row[9]
                )
                for row in rows
            ]
        
        except Exception as e:
            logger.warning(f"Failed to get goal queue: {e}")
            return []
    
    def update_goal_status(
        self,
        goal_type: str,
        target_file: Optional[Path],
        status: str,
        iteration_id: Optional[str] = None
    ) -> bool:
        """Update goal status."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE autonomous_goals
                SET status = ?, iteration_id = ?
                WHERE goal_type = ? AND target_file = ? AND status = 'pending'
            ''', (status, iteration_id, goal_type, str(target_file) if target_file else None))
            
            conn.commit()
            conn.close()
            
            return True
        
        except Exception as e:
            logger.warning(f"Failed to update goal status: {e}")
            return False
    
    def bump_priority(self, goal_type: str, target_file: Optional[Path]) -> bool:
        """Bump goal priority (human override)."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE autonomous_goals
                SET priority_score = priority_score + 20
                WHERE goal_type = ? AND target_file = ?
            ''', (goal_type, str(target_file) if target_file else None))
            
            conn.commit()
            conn.close()
            
            return True
        
        except Exception as e:
            logger.warning(f"Failed to bump priority: {e}")
            return False
    
    def defer_goal(self, goal_type: str, target_file: Optional[Path]) -> bool:
        """Defer goal to later (human override)."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE autonomous_goals
                SET priority_score = priority_score - 10
                WHERE goal_type = ? AND target_file = ?
            ''', (goal_type, str(target_file) if target_file else None))
            
            conn.commit()
            conn.close()
            
            return True
        
        except Exception as e:
            logger.warning(f"Failed to defer goal: {e}")
            return False
    
    def delete_goal(self, goal_type: str, target_file: Optional[Path]) -> bool:
        """Delete a goal (human override)."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM autonomous_goals
                WHERE goal_type = ? AND target_file = ?
            ''', (goal_type, str(target_file) if target_file else None))
            
            conn.commit()
            conn.close()
            
            return True
        
        except Exception as e:
            logger.warning(f"Failed to delete goal: {e}")
            return False


# Factory function
def create_goal_generator(config: Optional[AIWorkerConfig] = None) -> GoalGenerator:
    """Create and return a GoalGenerator instance."""
    return GoalGenerator(config)


try:
    goal_generator: GoalGenerator | None = create_goal_generator()
except Exception:
    logger.exception("Failed to initialize global goal_generator")
    goal_generator = None
