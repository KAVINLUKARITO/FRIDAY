"""Tests for the knowledge graph memory."""

from __future__ import annotations

import unittest

from aiworker.knowledge.knowledge_graph import knowledge_graph


class KnowledgeGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        knowledge_graph.reset()

    def test_graph_stores_concepts_skills_relationships_and_patterns(self) -> None:
        knowledge_graph.add_concept("planning", domain="reasoning")
        knowledge_graph.add_skill("patching", mastery=0.8)
        knowledge_graph.add_experience_pattern("successful_validation", confidence=0.9)
        knowledge_graph.add_relationship("planning", "patching", "supports", weight=0.7)
        snapshot = knowledge_graph.snapshot()
        self.assertEqual(snapshot["counts"]["concepts"], 1)
        self.assertEqual(snapshot["counts"]["skills"], 1)
        self.assertEqual(snapshot["counts"]["experience_patterns"], 1)
        self.assertEqual(snapshot["counts"]["relationships"], 1)


if __name__ == "__main__":
    unittest.main()
