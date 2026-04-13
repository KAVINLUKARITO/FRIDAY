"""
AIWorker Resource Prediction Model - Phase 4 Autonomous Intelligence

Predicts resource needs before execution to prevent OOM.

Input features (from iteration history):
- Target file: size, complexity, language
- Task type: refactor, optimize, add_feature, fix_bug
- Model used: mistral vs deepseek
- Historical: similar tasks memory/time usage

Prediction models (simple, no ML libraries):
- Linear regression: file_size → memory_gb
- Decision tree: task_type + model → time_estimate
- Conservative: max(observed) * 1.2 safety factor

Pre-execution checks:
- If predicted_memory + current_usage > 26GB: Reject or split
- If risk_level == "high": Require human confirmation
- If duration > 30 min: Schedule during low-activity period

Dynamic adaptation:
- During execution, compare actual vs predicted
- If trending over prediction: Pause, checkpoint, request decision
- Update model with actual results (online learning)
"""

import json
import logging
import sqlite3
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from aiworker.config import AIWorkerConfig

logger = logging.getLogger("aiworker.predictor")


@dataclass
class ResourcePrediction:
    """A resource usage prediction."""
    estimated_memory_gb: float
    estimated_duration_minutes: float
    confidence: float
    risk_level: str  # "low", "medium", "high"
    recommendation: str  # "proceed", "split_task", "use_lighter_model"
    safety_factor: float = 1.2


@dataclass
class TaskFeatures:
    """Features used for prediction."""
    file_size_bytes: int
    file_complexity: int  # Lines of code / branching points
    task_type: str
    model_name: str
    target_language: str = "python"


class ResourcePredictor:
    """
    Predicts resource needs for tasks to prevent OOM.
    
    Uses simple statistical models (linear regression, decision trees)
    without external ML libraries to stay within 32GB constraint.
    """
    
    # Risk thresholds
    MEMORY_LOW_GB = 20.0
    MEMORY_MEDIUM_GB = 24.0
    MEMORY_HIGH_GB = 26.0
    
    DURATION_SHORT_MIN = 10.0
    DURATION_MEDIUM_MIN = 20.0
    DURATION_LONG_MIN = 30.0
    
    def __init__(self, config: Optional[AIWorkerConfig] = None):
        self.config = config or AIWorkerConfig.from_env()
        self.base_path = Path(self.config.base_path)
        
        # Model parameters (learned from history)
        self._memory_coefficient = 0.001  # bytes to GB conversion
        self._memory_intercept = 2.0  # Base memory overhead
        self._duration_coefficient = 0.01  # Complexity to minutes
        self._duration_intercept = 5.0  # Base duration
        
        # Initialize database
        self._init_database()
        
        # Load learned parameters
        self._load_model_params()
        
        logger.info("ResourcePredictor initialized")
    
    def _init_database(self):
        """Initialize SQLite database for predictions."""
        db_path = self.base_path / "data" / "predictions.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                iteration_id TEXT,
                file_size_bytes INTEGER,
                file_complexity INTEGER,
                task_type TEXT,
                model_name TEXT,
                predicted_memory_gb REAL,
                predicted_duration_min REAL,
                actual_memory_gb REAL,
                actual_duration_min REAL,
                accuracy_error_pct REAL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS model_params (
                param_name TEXT PRIMARY KEY,
                param_value REAL,
                updated_at REAL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def _get_db_path(self) -> Path:
        """Get database path."""
        return self.base_path / "data" / "predictions.db"
    
    def _load_model_params(self):
        """Load learned model parameters from database."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('SELECT param_name, param_value FROM model_params')
            params = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()
            
            if 'memory_coefficient' in params:
                self._memory_coefficient = params['memory_coefficient']
            if 'memory_intercept' in params:
                self._memory_intercept = params['memory_intercept']
            if 'duration_coefficient' in params:
                self._duration_coefficient = params['duration_coefficient']
            if 'duration_intercept' in params:
                self._duration_intercept = params['duration_intercept']
            
            logger.debug(f"Loaded model params: {params}")
        
        except Exception as e:
            logger.debug(f"Failed to load model params: {e}")
    
    def _save_model_params(self):
        """Save learned model parameters to database."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            params = [
                ('memory_coefficient', self._memory_coefficient),
                ('memory_intercept', self._memory_intercept),
                ('duration_coefficient', self._duration_coefficient),
                ('duration_intercept', self._duration_intercept),
            ]
            
            for name, value in params:
                cursor.execute('''
                    INSERT OR REPLACE INTO model_params (param_name, param_value, updated_at)
                    VALUES (?, ?, ?)
                ''', (name, value, time.time()))
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.warning(f"Failed to save model params: {e}")
    
    def _get_historical_data(
        self,
        task_type: Optional[str] = None,
        limit: int = 50
    ) -> list[dict]:
        """Get historical prediction data for similar tasks."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            if task_type:
                cursor.execute('''
                    SELECT * FROM predictions
                    WHERE task_type = ? AND actual_memory_gb IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (task_type, limit))
            else:
                cursor.execute('''
                    SELECT * FROM predictions
                    WHERE actual_memory_gb IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [
                {
                    'file_size_bytes': row[4],
                    'file_complexity': row[5],
                    'task_type': row[6],
                    'model_name': row[7],
                    'predicted_memory_gb': row[8],
                    'predicted_duration_min': row[9],
                    'actual_memory_gb': row[10],
                    'actual_duration_min': row[11],
                }
                for row in rows
            ]
        
        except Exception as e:
            logger.debug(f"Failed to get historical data: {e}")
            return []
    
    def _calculate_file_complexity(self, file_path: Path) -> int:
        """Calculate file complexity metric."""
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            lines = content.split('\n')
            
            # Simple complexity: lines + branching points
            branching = content.count('if ') + content.count('for ') + content.count('while ')
            complexity = len(lines) + branching
            
            return complexity
        
        except Exception:
            return 100  # Default
    
    def predict(
        self,
        target_file: Path,
        task_type: str,
        model_name: str = "default"
    ) -> ResourcePrediction:
        """
        Predict resource needs for a task.
        
        Args:
            target_file: Path to file being modified
            task_type: Type of task (refactor, optimize, etc.)
            model_name: Model to be used
            
        Returns:
            ResourcePrediction with estimates and recommendations
        """
        # Get file features
        file_size = target_file.stat().st_size if target_file.exists() else 1000
        complexity = self._calculate_file_complexity(target_file) if target_file.exists() else 100
        
        features = TaskFeatures(
            file_size_bytes=file_size,
            file_complexity=complexity,
            task_type=task_type,
            model_name=model_name
        )
        
        # Get historical data for this task type
        historical = self._get_historical_data(task_type)
        
        # Predict memory using linear model
        memory_prediction = self._predict_memory(features, historical)
        
        # Predict duration using task type + complexity
        duration_prediction = self._predict_duration(features, historical)
        
        # Calculate confidence based on historical data availability
        confidence = min(1.0, len(historical) / 20.0)
        
        # Determine risk level
        risk_level = self._assess_risk(memory_prediction, duration_prediction)
        
        # Generate recommendation
        recommendation = self._generate_recommendation(
            memory_prediction, duration_prediction, risk_level
        )
        
        # Persist prediction
        self._persist_prediction(features, memory_prediction, duration_prediction)
        
        return ResourcePrediction(
            estimated_memory_gb=memory_prediction,
            estimated_duration_minutes=duration_prediction,
            confidence=confidence,
            risk_level=risk_level,
            recommendation=recommendation
        )
    
    def _predict_memory(
        self,
        features: TaskFeatures,
        historical: list[dict]
    ) -> float:
        """Predict memory usage."""
        # Base prediction from linear model
        base_prediction = (
            features.file_size_bytes * self._memory_coefficient +
            self._memory_intercept
        )
        
        # Adjust for task type
        task_multipliers = {
            'refactor': 1.0,
            'optimize': 1.2,  # Optimization may need more memory for analysis
            'add_feature': 1.1,
            'fix_bug': 0.9,
            'add_tests': 0.8,
        }
        multiplier = task_multipliers.get(features.task_type, 1.0)
        
        prediction = base_prediction * multiplier
        
        # If we have historical data, blend with average
        if historical:
            historical_avg = statistics.mean(h['actual_memory_gb'] for h in historical)
            # Weight: 60% model, 40% historical average
            prediction = 0.6 * prediction + 0.4 * historical_avg
        
        # Apply safety factor
        return prediction * 1.2
    
    def _predict_duration(
        self,
        features: TaskFeatures,
        historical: list[dict]
    ) -> float:
        """Predict duration in minutes."""
        # Base prediction from complexity
        base_prediction = (
            features.file_complexity * self._duration_coefficient +
            self._duration_intercept
        )
        
        # Adjust for task type
        task_multipliers = {
            'refactor': 1.2,
            'optimize': 1.5,  # Optimization takes longer
            'add_feature': 1.3,
            'fix_bug': 0.8,
            'add_tests': 0.7,
        }
        multiplier = task_multipliers.get(features.task_type, 1.0)
        
        prediction = base_prediction * multiplier
        
        # If we have historical data, blend with average
        if historical:
            historical_avg = statistics.mean(h['actual_duration_min'] for h in historical)
            prediction = 0.6 * prediction + 0.4 * historical_avg
        
        return prediction
    
    def _assess_risk(
        self,
        memory_gb: float,
        duration_min: float
    ) -> str:
        """Assess risk level based on predictions."""
        # Memory-based risk
        if memory_gb >= self.MEMORY_HIGH_GB:
            return "high"
        elif memory_gb >= self.MEMORY_MEDIUM_GB:
            return "medium"
        
        # Duration-based risk
        if duration_min >= self.DURATION_LONG_MIN:
            return "medium"
        
        return "low"
    
    def _generate_recommendation(
        self,
        memory_gb: float,
        duration_min: float,
        risk_level: str
    ) -> str:
        """Generate recommendation based on predictions."""
        if risk_level == "high":
            if memory_gb >= self.MEMORY_HIGH_GB:
                return "split_task"
            return "use_lighter_model"
        
        if risk_level == "medium":
            if duration_min >= self.DURATION_LONG_MIN:
                return "schedule_off_peak"
            return "proceed_with_caution"
        
        return "proceed"
    
    def _persist_prediction(
        self,
        features: TaskFeatures,
        memory_gb: float,
        duration_min: float
    ):
        """Persist prediction for later comparison."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO predictions 
                (timestamp, file_size_bytes, file_complexity, task_type, model_name,
                 predicted_memory_gb, predicted_duration_min)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                time.time(),
                features.file_size_bytes,
                features.file_complexity,
                features.task_type,
                features.model_name,
                memory_gb,
                duration_min
            ))
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.debug(f"Failed to persist prediction: {e}")
    
    def record_actual(
        self,
        iteration_id: str,
        actual_memory_gb: float,
        actual_duration_min: float
    ):
        """
        Record actual resource usage for online learning.
        
        Args:
            iteration_id: The iteration ID
            actual_memory_gb: Actual memory used
            actual_duration_min: Actual duration in minutes
        """
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            # Find the prediction for this iteration
            cursor.execute('''
                SELECT id, predicted_memory_gb, predicted_duration_min
                FROM predictions
                WHERE iteration_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
            ''', (iteration_id,))
            
            row = cursor.fetchone()
            
            if row:
                pred_id = row[0]
                pred_memory = row[1]
                pred_duration = row[2]
                
                # Calculate error
                memory_error = abs(actual_memory_gb - pred_memory) / max(pred_memory, 0.001) * 100
                duration_error = abs(actual_duration_min - pred_duration) / max(pred_duration, 0.001) * 100
                avg_error = (memory_error + duration_error) / 2
                
                # Update prediction with actuals
                cursor.execute('''
                    UPDATE predictions
                    SET actual_memory_gb = ?,
                        actual_duration_min = ?,
                        accuracy_error_pct = ?
                    WHERE id = ?
                ''', (actual_memory_gb, actual_duration_min, avg_error, pred_id))
                
                conn.commit()
                
                # Online learning: adjust model parameters
                self._update_model_params(pred_memory, actual_memory_gb)
            
            conn.close()
        
        except Exception as e:
            logger.debug(f"Failed to record actual: {e}")
    
    def _update_model_params(self, predicted: float, actual: float):
        """Update model parameters based on prediction error."""
        # Simple online learning: adjust coefficient slightly
        error = actual - predicted
        
        # Learning rate
        alpha = 0.01
        
        # Adjust coefficient
        if predicted > 0:
            adjustment = alpha * (error / predicted)
            self._memory_coefficient *= (1 + adjustment)
            
            # Keep within reasonable bounds
            self._memory_coefficient = max(0.0001, min(0.01, self._memory_coefficient))
            
            # Save updated params
            self._save_model_params()
    
    def get_accuracy_stats(self, days: int = 7) -> dict:
        """Get prediction accuracy statistics."""
        try:
            cutoff = time.time() - (days * 24 * 3600)
            
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    COUNT(*) as total,
                    AVG(accuracy_error_pct) as avg_error,
                    MIN(accuracy_error_pct) as min_error,
                    MAX(accuracy_error_pct) as max_error
                FROM predictions
                WHERE timestamp > ? AND accuracy_error_pct IS NOT NULL
            ''', (cutoff,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row and row[0] > 0:
                return {
                    'total_predictions': row[0],
                    'avg_error_percent': row[1],
                    'min_error_percent': row[2],
                    'max_error_percent': row[3],
                    'within_20_percent': row[1] <= 20.0 if row[1] else False
                }
        
        except Exception as e:
            logger.debug(f"Failed to get accuracy stats: {e}")
        
        return {
            'total_predictions': 0,
            'avg_error_percent': None,
            'min_error_percent': None,
            'max_error_percent': None,
            'within_20_percent': False
        }
    
    def can_execute_safely(
        self,
        target_file: Path,
        task_type: str,
        current_memory_gb: float
    ) -> tuple[bool, str]:
        """
        Check if task can be executed safely.
        
        Returns:
            (can_execute, reason) tuple
        """
        prediction = self.predict(target_file, task_type)
        
        total_memory = prediction.estimated_memory_gb + current_memory_gb
        
        if total_memory > 28.0:
            return False, f"Predicted total memory {total_memory:.1f}GB exceeds 28GB limit"
        
        if prediction.risk_level == "high":
            return False, f"High risk prediction: {prediction.recommendation}"
        
        return True, "Safe to proceed"


# Factory function
def create_resource_predictor(config: Optional[AIWorkerConfig] = None) -> ResourcePredictor:
    """Create and return a ResourcePredictor instance."""
    return ResourcePredictor(config)
