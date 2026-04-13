"""Simple in-memory knowledge graph."""

from __future__ import annotations

from copy import deepcopy
import threading
from typing import Any


class KnowledgeGraph:
    """Stores concepts, skills, relationships, and experience patterns."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._concepts: dict[str, dict[str, Any]] = {}
        self._skills: dict[str, dict[str, Any]] = {}
        self._relationships: list[dict[str, Any]] = []
        self._experience_patterns: dict[str, dict[str, Any]] = {}

    def add_concept(self, name: str, **metadata: Any) -> dict[str, Any]:
        with self._lock:
            concept = {"name": name, **metadata}
            self._concepts[name] = concept
            return dict(concept)

    def add_skill(self, name: str, mastery: float = 0.0, **metadata: Any) -> dict[str, Any]:
        with self._lock:
            skill = {"name": name, "mastery": round(max(0.0, min(1.0, mastery)), 4), **metadata}
            self._skills[name] = skill
            return dict(skill)

    def add_relationship(
        self,
        source: str,
        target: str,
        relation: str,
        *,
        weight: float = 1.0,
    ) -> dict[str, Any]:
        rel = {
            "source": source,
            "target": target,
            "relation": relation,
            "weight": round(max(0.0, min(1.0, weight)), 4),
        }
        with self._lock:
            self._relationships.append(rel)
        return dict(rel)

    def add_experience_pattern(self, name: str, **metadata: Any) -> dict[str, Any]:
        with self._lock:
            pattern = {"name": name, **metadata}
            self._experience_patterns[name] = pattern
            return dict(pattern)

    def record_experience(
        self,
        *,
        concept: str,
        skill: str,
        relationship: str,
        pattern: str,
        confidence: float,
    ) -> dict[str, Any]:
        self.add_concept(concept)
        self.add_skill(skill, mastery=confidence)
        self.add_experience_pattern(pattern, confidence=round(max(0.0, min(1.0, confidence)), 4))
        return self.add_relationship(concept, skill, relationship, weight=confidence)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "concepts": deepcopy(self._concepts),
                "skills": deepcopy(self._skills),
                "relationships": deepcopy(self._relationships),
                "experience_patterns": deepcopy(self._experience_patterns),
                "counts": {
                    "concepts": len(self._concepts),
                    "skills": len(self._skills),
                    "relationships": len(self._relationships),
                    "experience_patterns": len(self._experience_patterns),
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._concepts.clear()
            self._skills.clear()
            self._relationships.clear()
            self._experience_patterns.clear()


knowledge_graph = KnowledgeGraph()
