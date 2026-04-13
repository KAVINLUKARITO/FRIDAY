"""Unit tests for the conversational AIWorker interface."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from aiworker.chat.interface import AIWorkerChat, Intent, IntentClassifier, ProgressNarrator
from aiworker.config import AIWorkerConfig
from aiworker.governance.audit import create_event
from aiworker.learning.models import Lesson, _new_lesson_id, _utcnow_iso
from aiworker.learning.store import LearningStore
from aiworker.memory.database import Database


class _ChatBackend:
    def __init__(self, response: str = "I can help with that.") -> None:
        self.response = response

    def generate(self, prompt: str) -> str:
        del prompt
        return self.response


class ChatInterfaceTests(unittest.TestCase):
    def test_classifier_detects_run_goal(self) -> None:
        classifier = IntentClassifier()
        self.assertEqual(classifier.classify("fix auth"), Intent.RUN_GOAL)

    def test_narrator_maps_known_events(self) -> None:
        narrator = ProgressNarrator()
        event = create_event("validation", "warning", "validation_failed", "bad patch")
        self.assertIn("doesn't pass validation", narrator.narrate(event) or "")

    def test_run_goal_asks_for_files_then_starts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AIWorkerConfig(db_path=f"{tmpdir}/db.sqlite", workspace_path=tmpdir)
            chat = AIWorkerChat(config=config, patch_generator=_ChatBackend())
            response = chat.chat("fix auth")
            self.assertIn("Which files", response)

            with patch.object(AIWorkerChat, "_run_controller_thread") as run_thread:
                response = chat.chat("all")
            self.assertIn("I'm on it", response)
            run_thread.assert_called_once()

    def test_show_memory_summarises_lessons(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AIWorkerConfig(db_path=f"{tmpdir}/db.sqlite", workspace_path=tmpdir)
            database = Database(config.db_path)
            database.initialise()
            store = LearningStore(database)
            store.insert_lesson(
                Lesson(
                    lesson_id=_new_lesson_id(),
                    category="success_pattern",
                    summary="Cache token lookups",
                    detail="Caching removed one query",
                    confidence=0.8,
                    source_attempt_ids=("attempt-1",),
                    source_goal="improve auth",
                    applicable_goal_keywords=("auth",),
                    created_at=_utcnow_iso(),
                )
            )
            chat = AIWorkerChat(config=config, patch_generator=_ChatBackend())
            response = chat.chat("what have you learned?")
            self.assertIn("Cache token lookups", response)

    def test_handle_chat_uses_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AIWorkerConfig(db_path=f"{tmpdir}/db.sqlite", workspace_path=tmpdir)
            chat = AIWorkerChat(config=config, patch_generator=_ChatBackend("Direct answer"))
            self.assertEqual(chat.chat("hello"), "Direct answer")


if __name__ == "__main__":
    unittest.main()
