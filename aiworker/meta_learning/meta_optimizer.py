"""
AIWorker Meta-Learning Optimizer - Phase 4 Autonomous Intelligence

Analyzes iteration outcomes and recommends strategy improvements.

Data sources:
- SQLite: iteration_history (success/failure, duration, memory peak)
- SQLite: patch_history (acceptance rate, test pass rate, safety tier reached)
- SQLite: telemetry_samples (resource usage patterns)
- Git: code changes over time (complexity trends)

Analysis methods (simple statistics, no ML libraries):
- Success pattern mining: What preceded successful patches?
- Failure clustering: Common causes of rejection
- Resource efficiency: Memory/time tradeoffs by task type
- Strategy effectiveness: Which approaches yield better outcomes?

Integration:
- Called by handle_learn() after each iteration
- Stores recommendations in SQLite: strategy_recommendations
- SequentialEngine checks for pending recommendations before PLAN state
"""

import json
import logging
import sqlite3
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from aiworker.config import AIWorkerConfig

logger = logging.getLogger("aiworker.meta_learning")


@dataclass
class StrategyRecommendation:
    """A strategy optimization recommendation."""
    target: str  # "model_selection", "patch_size", "research_depth", etc.
    current_value: Any
    recommended_value: Any
    confidence: float  # 0.0-1.0 based on data quality
    rationale: str
    expected_improvement: str  # "20% faster", "15% less memory", etc.
    created_at: float = field(default_factory=time.time)
    applied: bool = False
    applied_at: Optional[float] = None
    actual_improvement: Optional[str] = None


@dataclass
class PerformanceMetrics:
    """Aggregated performance metrics."""
    total_iterations: int
    success_rate: float
    avg_duration_minutes: float
    avg_memory_gb: float
    failure_breakdown: dict[str, int]  # reason -> count
    trend_direction: str  # "improving", "stable", "degrading"


class MetaLearningOptimizer:
    """
    Analyzes AIWorker performance and recommends strategy improvements.
    
    Uses simple statistical analysis (mean, correlation, trend detection)
    to stay within 32GB constraint - no external ML libraries.
    """
    
    def __init__(self, config: Optional[AIWorkerConfig] = None):
        self.config = config or AIWorkerConfig.from_env()
        self.base_path = Path(self.config.base_path)
        
        # Analysis windows
        self.short_window_days = 1
        self.medium_window_days = 7
        self.long_window_days = 30
        
        # Minimum samples for reliable analysis
        self.min_samples = 5
        
        # Initialize database
        self._init_database()
        
        logger.info("MetaLearningOptimizer initialized")
    
    def _init_database(self):
        """Initialize SQLite database for recommendations."""
        db_path = self.base_path / "data" / "meta_learning.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                target TEXT NOT NULL,
                current_value TEXT,
                recommended_value TEXT,
                confidence REAL,
                rationale TEXT,
                expected_improvement TEXT,
                applied BOOLEAN DEFAULT 0,
                applied_at REAL,
                actual_improvement TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS analysis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                analysis_type TEXT NOT NULL,
                findings TEXT,
                recommendations_generated INTEGER
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_recommendations_target 
            ON strategy_recommendations(target)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_recommendations_applied 
            ON strategy_recommendations(applied)
        ''')
        
        conn.commit()
        conn.close()
    
    def _get_db_path(self) -> Path:
        """Get database path."""
        return self.base_path / "data" / "meta_learning.db"
    
    def _get_iterations_data(self, days: int) -> list[dict]:
        """Get iteration history from SQLite."""
        try:
            cutoff = time.time() - (days * 24 * 3600)
            
            # Try checkpoints database first
            checkpoint_db = Path(self.config.checkpoint_db)
            if checkpoint_db.exists():
                conn = sqlite3.connect(str(checkpoint_db))
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT iteration_id, state, goal, started_at, 
                           completed_at, success, error_count, data
                    FROM iterations
                    WHERE started_at > ?
                    ORDER BY started_at DESC
                ''', (cutoff,))
                
                rows = cursor.fetchall()
                conn.close()
                
                return [
                    {
                        'iteration_id': row[0],
                        'state': row[1],
                        'goal': row[2],
                        'started_at': row[3],
                        'completed_at': row[4],
                        'success': row[5],
                        'error_count': row[6],
                        'data': json.loads(row[7]) if row[7] else {}
                    }
                    for row in rows
                ]
        
        except Exception as e:
            logger.debug(f"Failed to get iterations data: {e}")
        
        return []
    
    def _get_telemetry_data(self, days: int) -> list[dict]:
        """Get telemetry samples from SQLite."""
        try:
            cutoff = time.time() - (days * 24 * 3600)
            
            telemetry_db = self.base_path / "data" / "telemetry.db"
            if telemetry_db.exists():
                conn = sqlite3.connect(str(telemetry_db))
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT timestamp, metric_type, value, unit
                    FROM telemetry_samples
                    WHERE timestamp > ?
                    ORDER BY timestamp DESC
                ''', (cutoff,))
                
                rows = cursor.fetchall()
                conn.close()
                
                return [
                    {
                        'timestamp': row[0],
                        'metric_type': row[1],
                        'value': row[2],
                        'unit': row[3]
                    }
                    for row in rows
                ]
        
        except Exception as e:
            logger.debug(f"Failed to get telemetry data: {e}")
        
        return []
    
    def _calculate_trend(self, values: list[float]) -> str:
        """Calculate trend direction from values."""
        if len(values) < 3:
            return "stable"
        
        # Split into halves
        mid = len(values) // 2
        first_half = values[:mid]
        second_half = values[mid:]
        
        if not first_half or not second_half:
            return "stable"
        
        first_avg = statistics.mean(first_half)
        second_avg = statistics.mean(second_half)
        
        # Determine trend
        diff_pct = abs(second_avg - first_avg) / max(first_avg, 0.001) * 100
        
        if diff_pct < 5:
            return "stable"
        elif second_avg > first_avg:
            return "increasing"
        else:
            return "decreasing"
    
    def _analyze_success_patterns(self, iterations: list[dict]) -> list[StrategyRecommendation]:
        """Mine patterns that precede successful iterations."""
        recommendations = []
        
        if len(iterations) < self.min_samples:
            return recommendations
        
        # Separate successful and failed iterations
        successful = [i for i in iterations if i.get('success')]
        failed = [i for i in iterations if not i.get('success')]
        
        if len(successful) < 3 or len(failed) < 2:
            return recommendations
        
        success_rate = len(successful) / len(iterations)
        
        # Analyze duration patterns
        success_durations = []
        for i in successful:
            if i.get('completed_at') and i.get('started_at'):
                duration = (i['completed_at'] - i['started_at']) / 60
                success_durations.append(duration)
        
        if success_durations:
            avg_success_duration = statistics.mean(success_durations)
            
            # Check if iterations are taking too long
            if avg_success_duration > 20:  # More than 20 minutes
                recommendations.append(StrategyRecommendation(
                    target="patch_size",
                    current_value="large_changes",
                    recommended_value="smaller_batches",
                    confidence=min(0.9, len(successful) / 20),
                    rationale=f"Successful iterations average {avg_success_duration:.1f} minutes. "
                              f"Smaller patches may complete faster with similar quality.",
                    expected_improvement="25% faster iterations"
                ))
        
        # Analyze model effectiveness (if data available)
        models_used = {}
        for i in iterations:
            model = i.get('data', {}).get('model_used', 'unknown')
            success = i.get('success', False)
            
            if model not in models_used:
                models_used[model] = {'success': 0, 'total': 0}
            
            models_used[model]['total'] += 1
            if success:
                models_used[model]['success'] += 1
        
        # Recommend model changes based on success rates
        for model, stats in models_used.items():
            if stats['total'] >= 5:
                rate = stats['success'] / stats['total']
                if rate < 0.5:
                    recommendations.append(StrategyRecommendation(
                        target="model_selection",
                        current_value=model,
                        recommended_value="alternative_model",
                        confidence=min(0.8, stats['total'] / 20),
                        rationale=f"Model '{model}' has only {rate*100:.0f}% success rate "
                                  f"({stats['success']}/{stats['total']}).",
                        expected_improvement="15% better success rate"
                    ))
        
        return recommendations
    
    def _analyze_resource_efficiency(self, iterations: list[dict], telemetry: list[dict]) -> list[StrategyRecommendation]:
        """Analyze memory/time tradeoffs and recommend optimizations."""
        recommendations = []
        
        # Get memory usage by iteration
        memory_by_iteration = {}
        for t in telemetry:
            if t['metric_type'] == 'memory_used_gb':
                # Approximate iteration by timestamp
                timestamp = t['timestamp']
                memory_by_iteration[timestamp] = t['value']
        
        if len(memory_by_iteration) < self.min_samples:
            return recommendations
        
        memory_values = list(memory_by_iteration.values())
        avg_memory = statistics.mean(memory_values)
        max_memory = max(memory_values)
        
        # High memory usage recommendation
        if max_memory > 26:  # Close to 28GB limit
            recommendations.append(StrategyRecommendation(
                target="memory_optimization",
                current_value=f"{avg_memory:.1f}GB avg",
                recommended_value="aggressive_cleanup",
                confidence=min(0.95, max_memory / 28),
                rationale=f"Peak memory usage reached {max_memory:.1f}GB, close to 28GB limit. "
                          f"Consider more frequent model unloading and cache clearing.",
                expected_improvement="20% lower peak memory"
            ))
        
        # Check for memory trend
        memory_trend = self._calculate_trend(memory_values)
        if memory_trend == "increasing":
            recommendations.append(StrategyRecommendation(
                target="memory_leak_detection",
                current_value="no_action",
                recommended_value="investigate_leaks",
                confidence=0.7,
                rationale="Memory usage is trending upward over time. "
                          "Possible memory leak in recent changes.",
                expected_improvement="Stable memory usage"
            ))
        
        return recommendations
    
    def _analyze_failure_clusters(self, iterations: list[dict]) -> list[StrategyRecommendation]:
        """Cluster failure causes and recommend mitigations."""
        recommendations = []
        
        failed = [i for i in iterations if not i.get('success')]
        
        if len(failed) < 3:
            return recommendations
        
        # Categorize failures
        failure_reasons = {}
        
        for i in failed:
            data = i.get('data', {})
            error = data.get('last_error', 'unknown')
            
            # Categorize
            if 'safety' in error.lower() or 'kill' in error.lower():
                reason = 'safety_rejection'
            elif 'test' in error.lower() or 'validation' in error.lower():
                reason = 'test_failure'
            elif 'timeout' in error.lower():
                reason = 'timeout'
            elif 'memory' in error.lower():
                reason = 'out_of_memory'
            else:
                reason = 'other'
            
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
        
        # Recommend based on most common failures
        for reason, count in sorted(failure_reasons.items(), key=lambda x: -x[1]):
            if reason == 'safety_rejection':
                recommendations.append(StrategyRecommendation(
                    target="safety_pre_check",
                    current_value="post_generation",
                    recommended_value="pre_generation",
                    confidence=min(0.85, count / 10),
                    rationale=f"{count} iterations failed safety cage. "
                              f"Pre-checking patches before generation may help.",
                    expected_improvement="30% fewer safety rejections"
                ))
            
            elif reason == 'test_failure':
                recommendations.append(StrategyRecommendation(
                    target="test_coverage",
                    current_value="baseline",
                    recommended_value="improved",
                    confidence=min(0.8, count / 10),
                    rationale=f"{count} iterations failed regression tests. "
                              f"Better test coverage may catch issues earlier.",
                    expected_improvement="20% fewer test failures"
                ))
            
            elif reason == 'timeout':
                recommendations.append(StrategyRecommendation(
                    target="timeout_handling",
                    current_value="fixed",
                    recommended_value="adaptive",
                    confidence=0.75,
                    rationale=f"{count} iterations timed out. "
                              f"Adaptive timeouts based on task complexity may help.",
                    expected_improvement="Fewer timeouts"
                ))
        
        return recommendations
    
    def analyze(self) -> list[StrategyRecommendation]:
        """
        Perform full analysis and generate recommendations.
        
        Returns:
            List of StrategyRecommendation objects
        """
        logger.info("Starting meta-learning analysis")
        
        # Gather data
        iterations = self._get_iterations_data(self.medium_window_days)
        telemetry = self._get_telemetry_data(self.medium_window_days)
        
        logger.debug(f"Analysis data: {len(iterations)} iterations, {len(telemetry)} telemetry samples")
        
        all_recommendations = []
        
        # Run analyses
        all_recommendations.extend(self._analyze_success_patterns(iterations))
        all_recommendations.extend(self._analyze_resource_efficiency(iterations, telemetry))
        all_recommendations.extend(self._analyze_failure_clusters(iterations))
        
        # Filter by confidence threshold
        min_confidence = 0.6
        filtered = [r for r in all_recommendations if r.confidence >= min_confidence]
        
        # Sort by confidence
        filtered.sort(key=lambda r: r.confidence, reverse=True)
        
        # Limit to top 5
        top_recommendations = filtered[:5]
        
        # Persist recommendations
        self._persist_recommendations(top_recommendations)
        
        logger.info(f"Analysis complete: {len(top_recommendations)} recommendations generated")
        
        return top_recommendations
    
    def _persist_recommendations(self, recommendations: list[StrategyRecommendation]):
        """Persist recommendations to database."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            for rec in recommendations:
                cursor.execute('''
                    INSERT INTO strategy_recommendations 
                    (created_at, target, current_value, recommended_value, 
                     confidence, rationale, expected_improvement, applied)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    rec.created_at,
                    rec.target,
                    str(rec.current_value),
                    str(rec.recommended_value),
                    rec.confidence,
                    rec.rationale,
                    rec.expected_improvement,
                    rec.applied
                ))
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.warning(f"Failed to persist recommendations: {e}")
    
    def get_pending_recommendations(self) -> list[StrategyRecommendation]:
        """Get recommendations that haven't been applied yet."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM strategy_recommendations
                WHERE applied = 0
                ORDER BY confidence DESC
            ''')
            
            rows = cursor.fetchall()
            conn.close()
            
            return [
                StrategyRecommendation(
                    target=row[3],
                    current_value=row[4],
                    recommended_value=row[5],
                    confidence=row[6],
                    rationale=row[7],
                    expected_improvement=row[8],
                    created_at=row[2]
                )
                for row in rows
            ]
        
        except Exception as e:
            logger.warning(f"Failed to get pending recommendations: {e}")
            return []
    
    def apply_recommendation(self, rec_id: int, actual_improvement: Optional[str] = None) -> bool:
        """Mark a recommendation as applied."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE strategy_recommendations
                SET applied = 1, applied_at = ?, actual_improvement = ?
                WHERE id = ?
            ''', (time.time(), actual_improvement, rec_id))
            
            conn.commit()
            conn.close()
            
            return True
        
        except Exception as e:
            logger.warning(f"Failed to apply recommendation: {e}")
            return False
    
    def get_performance_summary(self, days: int = 7) -> PerformanceMetrics:
        """Get performance summary for dashboard."""
        iterations = self._get_iterations_data(days)
        
        if not iterations:
            return PerformanceMetrics(
                total_iterations=0,
                success_rate=0.0,
                avg_duration_minutes=0.0,
                avg_memory_gb=0.0,
                failure_breakdown={},
                trend_direction="stable"
            )
        
        # Calculate metrics
        successful = [i for i in iterations if i.get('success')]
        success_rate = len(successful) / len(iterations) if iterations else 0.0
        
        durations = []
        for i in iterations:
            if i.get('completed_at') and i.get('started_at'):
                duration = (i['completed_at'] - i['started_at']) / 60
                durations.append(duration)
        
        avg_duration = statistics.mean(durations) if durations else 0.0
        
        # Failure breakdown
        failures = {}
        for i in iterations:
            if not i.get('success'):
                error = i.get('data', {}).get('last_error', 'unknown')
                failures[error] = failures.get(error, 0) + 1
        
        # Trend
        success_order = [1 if i.get('success') else 0 for i in iterations]
        trend = self._calculate_trend(success_order)
        trend_map = {
            "increasing": "improving",
            "decreasing": "degrading",
            "stable": "stable"
        }
        
        return PerformanceMetrics(
            total_iterations=len(iterations),
            success_rate=success_rate,
            avg_duration_minutes=avg_duration,
            avg_memory_gb=0.0,  # Would need telemetry correlation
            failure_breakdown=failures,
            trend_direction=trend_map.get(trend, "stable")
        )

    def reset(self) -> None:
        """Reset lightweight in-memory compatibility state."""
        self._last_report: dict[str, Any] = {}

    def optimize(self, attempts: Any) -> dict[str, Any]:
        """Compatibility optimizer used by the runtime dashboard tests."""
        outcomes: list[str] = [getattr(attempt, "outcome", "unknown") for attempt in attempts]
        failures = [outcome for outcome in outcomes if outcome != "success"]
        dominant = "none"
        if failures:
            dominant = max(set(failures), key=failures.count)

        failure_rate = len(failures) / max(1, len(outcomes))
        report = {
            "attempt_count": len(outcomes),
            "dominant_failure_mode": dominant,
            "recommended_strategy": "collect_more_evidence" if failure_rate >= 0.5 else "exploit_known_good_path",
            "exploration_rate": round(0.7 if failure_rate >= 0.5 else 0.3, 2),
            "exploitation_rate": round(0.3 if failure_rate >= 0.5 else 0.7, 2),
        }
        self._last_report = report
        return report

    def snapshot(self) -> dict[str, Any]:
        """Return dashboard-friendly optimizer state."""
        return getattr(self, "_last_report", {})


# Factory function
def create_meta_optimizer(config: Optional[AIWorkerConfig] = None) -> MetaLearningOptimizer:
    """Create and return a MetaLearningOptimizer instance."""
    return MetaLearningOptimizer(config)


try:
    meta_optimizer: MetaLearningOptimizer | None = create_meta_optimizer()
except Exception:
    logger.exception("Failed to initialize global meta_optimizer")
    meta_optimizer = None
