"""
AIWorker Skill Store - Phase 4 Autonomous Intelligence

Structured skill learning and mastery tracking.

Skills are capabilities AIWorker develops through practice:
- refactor_function, optimize_sql, add_tests, etc.

Mastery progression:
- Novice (0.0-0.3): First attempts, high failure rate
- Competent (0.3-0.7): Consistent success, moderate efficiency
- Expert (0.7-0.9): Fast, low resource use, high quality
- Master (0.9-1.0): Teaches others (generates documentation)

Learning mechanism:
- After each iteration, update relevant skill
- Success: +mastery based on efficiency (time, memory, quality)
- Failure: -mastery, record failure mode
- Pattern extraction: What differentiated success from failure?

Integration with curriculum:
- learning/curriculum.py reads skill_store
- Suggests practice tasks for weak skills
- Tracks progress through learning objectives
"""

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from aiworker.config import AIWorkerConfig

logger = logging.getLogger("aiworker.skills")


class MasteryLevel(Enum):
    """Mastery level categories."""
    NOVICE = "novice"           # 0.0-0.3
    COMPETENT = "competent"     # 0.3-0.7
    EXPERT = "expert"           # 0.7-0.9
    MASTER = "master"           # 0.9-1.0


@dataclass
class Skill:
    """A skill with mastery tracking."""
    name: str
    category: str  # "coding", "testing", "refactoring", "optimization"
    mastery_level: float  # 0.0-1.0
    attempts: int
    successes: int
    avg_duration_minutes: float
    avg_memory_gb: float
    last_practiced: float
    success_pattern: dict = field(default_factory=dict)
    failure_patterns: list = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.attempts == 0:
            return 0.0
        return self.successes / self.attempts
    
    @property
    def mastery_category(self) -> MasteryLevel:
        """Get mastery category."""
        if self.mastery_level >= 0.9:
            return MasteryLevel.MASTER
        elif self.mastery_level >= 0.7:
            return MasteryLevel.EXPERT
        elif self.mastery_level >= 0.3:
            return MasteryLevel.COMPETENT
        else:
            return MasteryLevel.NOVICE
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'category': self.category,
            'mastery_level': self.mastery_level,
            'mastery_category': self.mastery_category.value,
            'attempts': self.attempts,
            'successes': self.successes,
            'success_rate': self.success_rate,
            'avg_duration_minutes': self.avg_duration_minutes,
            'avg_memory_gb': self.avg_memory_gb,
            'last_practiced': self.last_practiced,
            'success_pattern': self.success_pattern,
            'failure_patterns': self.failure_patterns
        }


class SkillStore:
    """
    Manages skill learning and mastery tracking.
    
    Skills are automatically discovered from iteration history
    or defined in configuration. Mastery improves through practice.
    """
    
    # Skill categories
    CATEGORIES = ["coding", "testing", "refactoring", "optimization", "documentation"]
    
    # Predefined skills
    DEFAULT_SKILLS = [
        ("refactor_function", "refactoring"),
        ("optimize_sql", "optimization"),
        ("optimize_memory", "optimization"),
        ("add_tests", "testing"),
        ("improve_coverage", "testing"),
        ("add_type_hints", "coding"),
        ("add_docstrings", "documentation"),
        ("fix_error_handling", "coding"),
        ("reduce_complexity", "refactoring"),
        ("apply_pattern", "coding"),
    ]
    
    def __init__(self, config: Optional[AIWorkerConfig] = None):
        self.config = config or AIWorkerConfig.from_env()
        self.base_path = Path(self.config.base_path)
        
        # Initialize database
        self._init_database()
        
        # Ensure default skills exist
        self._ensure_default_skills()
        
        logger.info("SkillStore initialized")
    
    def _init_database(self):
        """Initialize SQLite database for skills."""
        db_path = self.base_path / "data" / "skills.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS skills (
                name TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                mastery_level REAL DEFAULT 0.0,
                attempts INTEGER DEFAULT 0,
                successes INTEGER DEFAULT 0,
                avg_duration_minutes REAL DEFAULT 0.0,
                avg_memory_gb REAL DEFAULT 0.0,
                last_practiced REAL,
                success_pattern TEXT,
                failure_patterns TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS skill_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name TEXT NOT NULL,
                timestamp REAL NOT NULL,
                mastery_before REAL,
                mastery_after REAL,
                iteration_id TEXT,
                outcome TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_skills_category 
            ON skills(category)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_skills_mastery 
            ON skills(mastery_level)
        ''')
        
        conn.commit()
        conn.close()
    
    def _get_db_path(self) -> Path:
        """Get database path."""
        return self.base_path / "data" / "skills.db"
    
    def _ensure_default_skills(self):
        """Ensure default skills exist in database."""
        for name, category in self.DEFAULT_SKILLS:
            if not self.get_skill(name):
                self._create_skill(name, category)
    
    def _create_skill(self, name: str, category: str) -> Skill:
        """Create a new skill in database."""
        skill = Skill(
            name=name,
            category=category,
            mastery_level=0.0,
            attempts=0,
            successes=0,
            avg_duration_minutes=0.0,
            avg_memory_gb=0.0,
            last_practiced=0.0
        )
        
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR IGNORE INTO skills 
                (name, category, mastery_level, attempts, successes, 
                 avg_duration_minutes, avg_memory_gb, last_practiced)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                skill.name, skill.category, skill.mastery_level,
                skill.attempts, skill.successes,
                skill.avg_duration_minutes, skill.avg_memory_gb,
                skill.last_practiced
            ))
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.warning(f"Failed to create skill: {e}")
        
        return skill
    
    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM skills WHERE name = ?', (name,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return Skill(
                    name=row[0],
                    category=row[1],
                    mastery_level=row[2],
                    attempts=row[3],
                    successes=row[4],
                    avg_duration_minutes=row[5],
                    avg_memory_gb=row[6],
                    last_practiced=row[7] if row[7] else 0.0,
                    success_pattern=json.loads(row[8]) if row[8] else {},
                    failure_patterns=json.loads(row[9]) if row[9] else []
                )
        
        except Exception as e:
            logger.warning(f"Failed to get skill: {e}")
        
        return None
    
    def get_all_skills(self, category: Optional[str] = None) -> list[Skill]:
        """Get all skills, optionally filtered by category."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            if category:
                cursor.execute('SELECT * FROM skills WHERE category = ?', (category,))
            else:
                cursor.execute('SELECT * FROM skills')
            
            rows = cursor.fetchall()
            conn.close()
            
            return [
                Skill(
                    name=row[0],
                    category=row[1],
                    mastery_level=row[2],
                    attempts=row[3],
                    successes=row[4],
                    avg_duration_minutes=row[5],
                    avg_memory_gb=row[6],
                    last_practiced=row[7] if row[7] else 0.0,
                    success_pattern=json.loads(row[8]) if row[8] else {},
                    failure_patterns=json.loads(row[9]) if row[9] else []
                )
                for row in rows
            ]
        
        except Exception as e:
            logger.warning(f"Failed to get skills: {e}")
            return []
    
    def update_skill(
        self,
        name: str,
        success: bool,
        duration_minutes: float,
        memory_gb: float,
        iteration_id: Optional[str] = None,
        pattern_data: Optional[dict] = None
    ) -> Skill:
        """
        Update skill after practice.
        
        Args:
            name: Skill name
            success: Whether the attempt succeeded
            duration_minutes: Time taken
            memory_gb: Memory used
            iteration_id: Associated iteration
            pattern_data: Success/failure pattern data
            
        Returns:
            Updated Skill
        """
        skill = self.get_skill(name)
        
        if not skill:
            # Auto-create skill
            category = self._infer_category(name)
            skill = self._create_skill(name, category)
        
        # Store old mastery for history
        mastery_before = skill.mastery_level
        
        # Update stats
        skill.attempts += 1
        skill.last_practiced = time.time()
        
        if success:
            skill.successes += 1
            
            # Calculate mastery gain based on efficiency
            # Faster and lower memory = more mastery
            time_factor = max(0.5, 1.0 - (duration_minutes / 60.0))  # Normalize to 1 hour
            memory_factor = max(0.5, 1.0 - (memory_gb / 20.0))  # Normalize to 20GB
            
            # Base gain for success
            base_gain = 0.05
            efficiency_bonus = (time_factor + memory_factor) / 2 * 0.03
            
            mastery_gain = base_gain + efficiency_bonus
            skill.mastery_level = min(1.0, skill.mastery_level + mastery_gain)
            
            # Update success pattern
            if pattern_data:
                skill.success_pattern.update(pattern_data)
        
        else:
            # Mastery loss for failure
            mastery_loss = 0.02
            skill.mastery_level = max(0.0, skill.mastery_level - mastery_loss)
            
            # Record failure pattern
            if pattern_data:
                skill.failure_patterns.append({
                    'timestamp': time.time(),
                    'data': pattern_data
                })
                # Keep only last 10 failures
                skill.failure_patterns = skill.failure_patterns[-10:]
        
        # Update averages
        if skill.attempts > 1:
            skill.avg_duration_minutes = (
                (skill.avg_duration_minutes * (skill.attempts - 1) + duration_minutes)
                / skill.attempts
            )
            skill.avg_memory_gb = (
                (skill.avg_memory_gb * (skill.attempts - 1) + memory_gb)
                / skill.attempts
            )
        else:
            skill.avg_duration_minutes = duration_minutes
            skill.avg_memory_gb = memory_gb
        
        # Persist skill
        self._persist_skill(skill)
        
        # Record history
        self._record_history(
            skill.name, mastery_before, skill.mastery_level,
            iteration_id, 'success' if success else 'failure'
        )
        
        logger.info(
            f"Skill '{name}' updated: mastery={skill.mastery_level:.2f}, "
            f"attempts={skill.attempts}, successes={skill.successes}"
        )
        
        return skill
    
    def _infer_category(self, skill_name: str) -> str:
        """Infer skill category from name."""
        category_keywords = {
            "testing": ["test", "coverage"],
            "refactoring": ["refactor", "complexity", "clean"],
            "optimization": ["optim", "performance", "memory", "speed"],
            "documentation": ["doc", "comment", "readme"],
            "coding": ["code", "function", "class", "type"]
        }
        
        skill_lower = skill_name.lower()
        
        for category, keywords in category_keywords.items():
            if any(kw in skill_lower for kw in keywords):
                return category
        
        return "coding"  # Default
    
    def _persist_skill(self, skill: Skill):
        """Persist skill to database."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE skills SET
                    mastery_level = ?,
                    attempts = ?,
                    successes = ?,
                    avg_duration_minutes = ?,
                    avg_memory_gb = ?,
                    last_practiced = ?,
                    success_pattern = ?,
                    failure_patterns = ?
                WHERE name = ?
            ''', (
                skill.mastery_level,
                skill.attempts,
                skill.successes,
                skill.avg_duration_minutes,
                skill.avg_memory_gb,
                skill.last_practiced,
                json.dumps(skill.success_pattern),
                json.dumps(skill.failure_patterns),
                skill.name
            ))
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.warning(f"Failed to persist skill: {e}")
    
    def _record_history(
        self,
        skill_name: str,
        mastery_before: float,
        mastery_after: float,
        iteration_id: Optional[str],
        outcome: str
    ):
        """Record skill change history."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO skill_history 
                (skill_name, timestamp, mastery_before, mastery_after, iteration_id, outcome)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                skill_name, time.time(), mastery_before, mastery_after,
                iteration_id, outcome
            ))
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.debug(f"Failed to record skill history: {e}")
    
    def get_skills_by_mastery(self, min_mastery: float = 0.0) -> list[Skill]:
        """Get skills filtered by minimum mastery level."""
        skills = self.get_all_skills()
        return [s for s in skills if s.mastery_level >= min_mastery]
    
    def get_weakest_skills(self, limit: int = 5) -> list[Skill]:
        """Get skills with lowest mastery for practice suggestions."""
        skills = self.get_all_skills()
        skills.sort(key=lambda s: s.mastery_level)
        return skills[:limit]
    
    def get_strongest_skills(self, limit: int = 5) -> list[Skill]:
        """Get skills with highest mastery for time-critical tasks."""
        skills = self.get_all_skills()
        skills.sort(key=lambda s: -s.mastery_level)
        return skills[:limit]
    
    def get_skill_summary(self) -> dict:
        """Get summary of all skills for dashboard."""
        skills = self.get_all_skills()
        
        if not skills:
            return {
                'total_skills': 0,
                'avg_mastery': 0.0,
                'by_category': {},
                'by_mastery_level': {}
            }
        
        # By category
        by_category = {}
        for skill in skills:
            cat = skill.category
            if cat not in by_category:
                by_category[cat] = {'count': 0, 'avg_mastery': 0.0}
            by_category[cat]['count'] += 1
            by_category[cat]['avg_mastery'] += skill.mastery_level
        
        for cat in by_category:
            by_category[cat]['avg_mastery'] /= by_category[cat]['count']
        
        # By mastery level
        by_level = {
            'novice': 0,
            'competent': 0,
            'expert': 0,
            'master': 0
        }
        
        for skill in skills:
            by_level[skill.mastery_category.value] += 1
        
        return {
            'total_skills': len(skills),
            'avg_mastery': sum(s.mastery_level for s in skills) / len(skills),
            'by_category': by_category,
            'by_mastery_level': by_level
        }
    
    def suggest_practice_tasks(self) -> list[dict]:
        """Suggest practice tasks for weak skills (for curriculum)."""
        weak_skills = self.get_weakest_skills(5)
        
        suggestions = []
        for skill in weak_skills:
            if skill.mastery_level < 0.7:  # Below expert
                suggestions.append({
                    'skill': skill.name,
                    'category': skill.category,
                    'current_mastery': skill.mastery_level,
                    'suggested_practice': f"Practice {skill.name} on small, safe tasks",
                    'target_mastery': min(1.0, skill.mastery_level + 0.2)
                })
        
        return suggestions


# Factory function
def create_skill_store(config: Optional[AIWorkerConfig] = None) -> SkillStore:
    """Create and return a SkillStore instance."""
    return SkillStore(config)
