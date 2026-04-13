"""Persistent skill store — Phase 2."""
from __future__ import annotations
import json
import sqlite3
import uuid
from typing import Any, List, Optional

from aiworker.learning.models import Skill


class SkillDatabase:
    """SQLite-backed skill database. Uses a single persistent connection for :memory:."""

    def __init__(self, path: str = ":memory:") -> None:
        self._path = path
        # For :memory: databases, use one persistent connection
        self._conn: Optional[sqlite3.Connection] = None
        if path == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.row_factory = sqlite3.Row

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = self._get_connection()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur

    def fetchall(self, sql: str, params: tuple = ()) -> list:
        return self._get_connection().execute(sql, params).fetchall()

    def fetchone(self, sql: str, params: tuple = ()):
        return self._get_connection().execute(sql, params).fetchone()

    def initialise(self) -> None:
        self.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                skill_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                examples TEXT NOT NULL DEFAULT '[]',
                success_contexts TEXT NOT NULL DEFAULT '[]',
                failure_contexts TEXT NOT NULL DEFAULT '[]',
                mastery_score REAL NOT NULL DEFAULT 0.0,
                attempt_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        self.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                pattern_id TEXT PRIMARY KEY,
                goal_fragment TEXT NOT NULL,
                strategy_used TEXT NOT NULL,
                outcome TEXT NOT NULL,
                score REAL NOT NULL,
                generalisation TEXT NOT NULL
            )
        """)


class SkillRepository:
    def __init__(self, db: SkillDatabase) -> None:
        self._db = db

    def upsert_skill(self, skill: Skill) -> Skill:
        self._db.execute("""
            INSERT INTO skills
                (skill_id, name, description, category, examples,
                 success_contexts, failure_contexts, mastery_score, attempt_count)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(skill_id) DO UPDATE SET
                mastery_score=excluded.mastery_score,
                attempt_count=excluded.attempt_count,
                success_contexts=excluded.success_contexts,
                failure_contexts=excluded.failure_contexts,
                examples=excluded.examples
        """, (
            skill.skill_id, skill.name, skill.description, skill.category,
            json.dumps(list(skill.examples)),
            json.dumps(list(skill.success_contexts)),
            json.dumps(list(skill.failure_contexts)),
            skill.mastery_score, skill.attempt_count,
        ))
        return skill

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        row = self._db.fetchone("SELECT * FROM skills WHERE skill_id = ?", (skill_id,))
        return self._row_to_skill(row) if row else None

    def get_all_skills(self) -> List[Skill]:
        rows = self._db.fetchall("SELECT * FROM skills ORDER BY mastery_score DESC")
        return [self._row_to_skill(r) for r in rows]

    def get_skills_by_category(self, category: str) -> List[Skill]:
        rows = self._db.fetchall("SELECT * FROM skills WHERE category = ?", (category,))
        return [self._row_to_skill(r) for r in rows]

    def get_skill_summary(self) -> dict[str, Any]:
        skills = self.get_all_skills()
        summary = {skill.name: round(skill.mastery_score, 4) for skill in skills}
        learning_progress = (
            round(sum(skill.mastery_score for skill in skills) / len(skills), 4)
            if skills
            else 0.0
        )
        return {
            "skills": summary,
            "learning_progress": learning_progress,
        }

    def record_attempt(self, skill_id: str, success: bool, score: float) -> Optional[Skill]:
        skill = self.get_skill(skill_id)
        if skill is None:
            return None
        new_count = skill.attempt_count + 1
        alpha = 0.3
        new_mastery = alpha * (1.0 if success else 0.0) + (1 - alpha) * skill.mastery_score
        new_mastery = max(0.0, min(1.0, new_mastery))
        updated = Skill(
            skill_id=skill.skill_id, name=skill.name, description=skill.description,
            category=skill.category, examples=skill.examples,
            success_contexts=skill.success_contexts, failure_contexts=skill.failure_contexts,
            mastery_score=round(new_mastery, 4), attempt_count=new_count,
        )
        return self.upsert_skill(updated)

    @staticmethod
    def _row_to_skill(row) -> Skill:
        return Skill(
            skill_id=row["skill_id"], name=row["name"], description=row["description"],
            category=row["category"],
            examples=tuple(json.loads(row["examples"])),
            success_contexts=tuple(json.loads(row["success_contexts"])),
            failure_contexts=tuple(json.loads(row["failure_contexts"])),
            mastery_score=float(row["mastery_score"]),
            attempt_count=int(row["attempt_count"]),
        )
