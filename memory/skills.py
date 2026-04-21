from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory.store import GOALS_PATH, MEMORY_PATH, _load_json, _load_records


SKILLS_PATH = Path("memory/skills.json")
SKILL_STOPWORDS = {"the", "a", "an", "all", "in", "to", "of", "and", "then", "current"}
GENERIC_SKILL_WORDS = {"list", "read", "write", "files", "file", "directory", "folder", "project", "workspace"}


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp_path.replace(path)


class SkillLibrary:
    def save_skill(self, name: str, steps: list[dict[str, Any]], avg_score: float) -> None:
        existing = self.find_skill(name, exact=True) or self.find_skill(name)
        skill = {
            "name": name,
            "steps": steps,
            "avg_score": avg_score,
            "saved_at": datetime.now(UTC).isoformat(),
            "use_count": int((existing or {}).get("use_count", 0)),
        }
        skills = self._load()
        existing_name = str((existing or {}).get("name", ""))
        skills = [item for item in skills if item.get("name") not in {name, existing_name}]
        skills.append(skill)
        _atomic_write(SKILLS_PATH, skills)

    def find_skill(self, task: str, *, exact: bool = False) -> dict[str, Any] | None:
        skills = self._load()
        normalized_task = str(task).strip().lower()
        for skill in skills:
            if str(skill.get("name", "")).strip().lower() == normalized_task:
                return skill
        if exact:
            return None
        task_words = self._tokenize(task)
        best: dict[str, Any] | None = None
        best_score = 0.0
        for skill in skills:
            skill_words = self._tokenize(str(skill.get("name", "")))
            if not task_words or not skill_words:
                continue
            discriminative_words = skill_words - GENERIC_SKILL_WORDS
            if discriminative_words and not (task_words & discriminative_words):
                continue
            if not discriminative_words:
                continue
            overlap = len(task_words & skill_words)
            union = len(task_words | skill_words)
            score = overlap / union if union else 0.0
            if score > best_score:
                best_score = score
                best = skill
        if best_score >= 0.75:
            return best
        return None

    def increment_use(self, name: str) -> None:
        skills = self._load()
        changed = False
        normalized_name = str(name).strip().lower()
        for skill in skills:
            if str(skill.get("name", "")).strip().lower() == normalized_name:
                skill["use_count"] = int(skill.get("use_count", 0)) + 1
                changed = True
        if changed:
            _atomic_write(SKILLS_PATH, skills)

    def promote_from_goals(self) -> int:
        goals = _load_json(GOALS_PATH, [])
        if not isinstance(goals, list):
            return 0
        promoted = 0
        existing_names = {str(skill.get("name", "")) for skill in self._load()}
        records = _load_records(MEMORY_PATH)
        for goal_record in goals:
            if not isinstance(goal_record, dict):
                continue
            goal_name = str(goal_record.get("goal", ""))[:50]
            if not goal_name or goal_name in existing_names:
                continue
            results = goal_record.get("results", [])
            sub_goals = goal_record.get("sub_goals", [])
            if not isinstance(results, list) or not isinstance(sub_goals, list):
                continue
            if not results or not all(bool(item.get("achieved")) for item in results if isinstance(item, dict)):
                continue
            steps: list[dict[str, Any]] = []
            for sub_goal in sub_goals:
                sub_goal_text = str(sub_goal).lower()
                matching = [
                    record
                    for record in records
                    if sub_goal_text in str(record.get("task", "")).lower() and bool(record.get("success"))
                ]
                if matching:
                    best = max(matching, key=lambda record: float(record.get("score", 0.0)))
                    steps.append(
                        {
                            "tool": str(best.get("tool", "")),
                            "arguments": {},
                            "score": float(best.get("score", 0.0)),
                        }
                    )
            if steps:
                avg = sum(step["score"] for step in steps) / len(steps)
                self.save_skill(goal_name, steps, avg)
                existing_names.add(goal_name)
                promoted += 1
        return promoted

    def _load(self) -> list[dict[str, Any]]:
        parsed = _load_json(SKILLS_PATH, [])
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, dict)]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        tokens = {token for token in re.findall(r"[a-z0-9_.-/]+", text.lower()) if token and token not in SKILL_STOPWORDS}
        return tokens
