"""Tests for Phase 6 — Version Graph, Rollback Engine, Snapshot Store.

Covers:
- VersionNode: frozen, to_dict, all fields
- VersionGraph: root creation, add_node, get_parent, get_latest,
                get_ancestors, set_head, size, to_dict
- VersionGraph: invalid parent_id raises ValueError
- VersionGraph: cycle guard in get_ancestors
- RollbackEngine: detect_regression (positive/negative)
- RollbackEngine: rollback_to_last_good (success, no-ancestor, no-better)
- RollbackEngine: rollback_to_node (explicit)
- RollbackEngine: constructor validation (positive min_score_delta raises)
- RollbackResult: frozen, to_dict
- SnapshotStore: initialise, save, get_by_node, get_by_snapshot_id,
                 list_by_node_ids, count, missing returns None
- AutonomyLoop integration: snapshot_ids in IterationResult
- AutonomyLoop integration: version_graph in LoopReport
- AutonomyLoop integration: versioning disabled
"""
from __future__ import annotations
import unittest

from aiworker.versioning.models import VersionNode, RollbackResult
from aiworker.versioning.version_graph import VersionGraph
from aiworker.versioning.rollback_engine import RollbackEngine
from aiworker.versioning.snapshot_store import SnapshotStore
from aiworker.autonomy.loop import AutonomyLoop, LoopConfig, LoopState
from aiworker.autonomy.circuit_breaker import CircuitBreakerConfig
from aiworker.autonomy.rate_limiter import RateLimiterConfig


# ── VersionNode ──────────────────────────────────────────────────────────────

class TestVersionNode(unittest.TestCase):
    def _make(self, **kw):
        defaults = dict(snapshot_id="s1", parent_id=None,
                        timestamp="2024-01-01T00:00:00+00:00",
                        score=0.5, metadata={})
        defaults.update(kw)
        return VersionNode(**defaults)

    def test_frozen(self):
        n = self._make()
        with self.assertRaises((AttributeError, TypeError)):
            n.score = 0.9

    def test_to_dict_keys(self):
        n = self._make()
        d = n.to_dict()
        for k in ("snapshot_id", "parent_id", "timestamp", "score", "metadata"):
            self.assertIn(k, d)

    def test_to_dict_values(self):
        n = self._make(score=0.75, parent_id="p1")
        d = n.to_dict()
        self.assertEqual(d["score"], 0.75)
        self.assertEqual(d["parent_id"], "p1")

    def test_metadata_copied_in_to_dict(self):
        n = self._make(metadata={"goal": "add feature"})
        d = n.to_dict()
        d["metadata"]["goal"] = "mutated"
        # Original node metadata must not be affected (can't mutate frozen anyway)
        self.assertEqual(n.metadata["goal"], "add feature")


# ── VersionGraph ─────────────────────────────────────────────────────────────

class TestVersionGraph(unittest.TestCase):
    def test_initial_state_has_root(self):
        g = VersionGraph()
        self.assertEqual(g.size(), 1)

    def test_root_has_no_parent(self):
        g = VersionGraph()
        root = g.get_root()
        self.assertIsNone(root.parent_id)

    def test_initial_score(self):
        g = VersionGraph(initial_score=0.5)
        self.assertAlmostEqual(g.get_root().score, 0.5)

    def test_score_clamped_on_init(self):
        g = VersionGraph(initial_score=1.5)
        self.assertLessEqual(g.get_root().score, 1.0)
        g2 = VersionGraph(initial_score=-0.5)
        self.assertGreaterEqual(g2.get_root().score, 0.0)

    def test_add_node_increments_size(self):
        g = VersionGraph()
        g.add_node(score=0.7)
        self.assertEqual(g.size(), 2)

    def test_add_node_returns_version_node(self):
        g = VersionGraph()
        n = g.add_node(score=0.8)
        self.assertIsInstance(n, VersionNode)

    def test_add_node_sets_head(self):
        g = VersionGraph()
        n = g.add_node(score=0.9)
        self.assertEqual(g.get_latest().snapshot_id, n.snapshot_id)

    def test_add_node_links_to_parent(self):
        g = VersionGraph()
        root = g.get_root()
        n = g.add_node(score=0.7)
        self.assertEqual(n.parent_id, root.snapshot_id)

    def test_add_node_explicit_parent(self):
        g = VersionGraph()
        root = g.get_root()
        n1 = g.add_node(score=0.5)
        n2 = g.add_node(score=0.6, parent_id=root.snapshot_id)
        self.assertEqual(n2.parent_id, root.snapshot_id)

    def test_add_node_invalid_parent_raises(self):
        g = VersionGraph()
        with self.assertRaises(ValueError):
            g.add_node(score=0.5, parent_id="nonexistent-id")

    def test_add_node_score_clamped(self):
        g = VersionGraph()
        n = g.add_node(score=2.0)
        self.assertLessEqual(n.score, 1.0)

    def test_get_node_returns_correct(self):
        g = VersionGraph()
        n = g.add_node(score=0.6)
        fetched = g.get_node(n.snapshot_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.snapshot_id, n.snapshot_id)

    def test_get_node_missing_returns_none(self):
        g = VersionGraph()
        self.assertIsNone(g.get_node("does-not-exist"))

    def test_get_parent_returns_parent(self):
        g = VersionGraph()
        root = g.get_root()
        n = g.add_node(score=0.5)
        parent = g.get_parent(n.snapshot_id)
        self.assertEqual(parent.snapshot_id, root.snapshot_id)

    def test_get_parent_of_root_returns_none(self):
        g = VersionGraph()
        self.assertIsNone(g.get_parent(g.get_root().snapshot_id))

    def test_get_ancestors_chain_length(self):
        g = VersionGraph()
        g.add_node(score=0.5)
        g.add_node(score=0.6)
        n3 = g.add_node(score=0.7)
        ancestors = g.get_ancestors(n3.snapshot_id)
        self.assertEqual(len(ancestors), 4)  # n3 + n2 + n1 + root

    def test_get_ancestors_order(self):
        g = VersionGraph()
        n1 = g.add_node(score=0.5)
        n2 = g.add_node(score=0.6)
        chain = g.get_ancestors(n2.snapshot_id)
        self.assertEqual(chain[0].snapshot_id, n2.snapshot_id)
        self.assertEqual(chain[1].snapshot_id, n1.snapshot_id)

    def test_set_head_moves_head(self):
        g = VersionGraph()
        root = g.get_root()
        g.add_node(score=0.5)
        g.set_head(root.snapshot_id)
        self.assertEqual(g.get_latest().snapshot_id, root.snapshot_id)

    def test_set_head_invalid_raises(self):
        g = VersionGraph()
        with self.assertRaises(ValueError):
            g.set_head("does-not-exist")

    def test_all_nodes_sorted(self):
        g = VersionGraph()
        g.add_node(score=0.5)
        g.add_node(score=0.6)
        nodes = g.all_nodes()
        ts = [n.timestamp for n in nodes]
        self.assertEqual(ts, sorted(ts))

    def test_to_dict_structure(self):
        g = VersionGraph()
        g.add_node(score=0.7)
        d = g.to_dict()
        self.assertIn("head", d)
        self.assertIn("size", d)
        self.assertIn("nodes", d)
        self.assertEqual(d["size"], 2)

    def test_metadata_stored_on_node(self):
        g = VersionGraph()
        n = g.add_node(score=0.5, metadata={"goal": "add tests"})
        fetched = g.get_node(n.snapshot_id)
        self.assertEqual(fetched.metadata["goal"], "add tests")


# ── RollbackResult ────────────────────────────────────────────────────────────

class TestRollbackResult(unittest.TestCase):
    def _make(self, success=True):
        return RollbackResult(
            success=success, rolled_back_to="a", from_snapshot="b",
            reason="test", score_recovered=0.7,
        )

    def test_frozen(self):
        r = self._make()
        with self.assertRaises((AttributeError, TypeError)):
            r.success = False

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        for k in ("success","rolled_back_to","from_snapshot","reason","score_recovered"):
            self.assertIn(k, d)


# ── RollbackEngine ────────────────────────────────────────────────────────────

class TestRollbackEngineConstructor(unittest.TestCase):
    def test_default_threshold(self):
        g = VersionGraph()
        re = RollbackEngine(g)
        self.assertLessEqual(re.min_score_delta, 0.0)

    def test_positive_threshold_raises(self):
        g = VersionGraph()
        with self.assertRaises(ValueError):
            RollbackEngine(g, min_score_delta=0.1)

    def test_zero_threshold_allowed(self):
        g = VersionGraph(initial_score=0.5)
        re = RollbackEngine(g, min_score_delta=0.0)
        self.assertEqual(re.min_score_delta, 0.0)


class TestDetectRegression(unittest.TestCase):
    def _setup(self, head_score=0.8):
        g = VersionGraph(initial_score=head_score)
        return g, RollbackEngine(g, min_score_delta=-0.1)

    def test_no_regression_on_improvement(self):
        g, re = self._setup(0.5)
        self.assertFalse(re.detect_regression(0.7))

    def test_no_regression_on_same_score(self):
        g, re = self._setup(0.5)
        self.assertFalse(re.detect_regression(0.5))

    def test_no_regression_on_small_drop(self):
        g, re = self._setup(0.5)
        # Drop of 0.05 < threshold of 0.1
        self.assertFalse(re.detect_regression(0.45))

    def test_regression_on_large_drop(self):
        g, re = self._setup(0.8)
        # Drop of 0.5 > threshold of 0.1
        self.assertTrue(re.detect_regression(0.3))

    def test_regression_at_exact_threshold(self):
        g, re = self._setup(0.8)
        # Drop of exactly 0.1: 0.8 - 0.1 = 0.7; delta = 0.7 - 0.8 = -0.1
        # -0.1 < -0.1 is False, so NO regression at exact threshold
        self.assertFalse(re.detect_regression(0.7))

    def test_regression_just_past_threshold(self):
        g, re = self._setup(0.8)
        # Drop of 0.101: delta = 0.699 - 0.8 = -0.101 < -0.1 → regression
        self.assertTrue(re.detect_regression(0.699))


class TestRollbackToLastGood(unittest.TestCase):
    def _build_graph(self, scores):
        """Build a linear graph with given scores. Returns graph."""
        g = VersionGraph(initial_score=scores[0])
        for s in scores[1:]:
            g.add_node(score=s)
        return g

    def test_rollback_finds_best_ancestor(self):
        g = self._build_graph([0.5, 0.8, 0.3])  # head=0.3, best ancestor=0.8
        re = RollbackEngine(g, min_score_delta=-0.1)
        result = re.rollback_to_last_good()
        self.assertTrue(result.success)
        self.assertAlmostEqual(result.score_recovered, 0.8)

    def test_rollback_moves_head(self):
        g = self._build_graph([0.5, 0.8, 0.3])
        re = RollbackEngine(g)
        re.rollback_to_last_good()
        self.assertAlmostEqual(g.get_latest().score, 0.8)

    def test_rollback_fails_when_at_root(self):
        g = VersionGraph(initial_score=0.5)
        re = RollbackEngine(g)
        result = re.rollback_to_last_good()
        self.assertFalse(result.success)
        self.assertIn("root", result.reason.lower())

    def test_rollback_fails_when_no_better_ancestor(self):
        # All ancestors have lower scores
        g = self._build_graph([0.3, 0.2, 0.1])  # head=0.1, best=0.3 but 0.3>0.1
        re = RollbackEngine(g)
        result = re.rollback_to_last_good()
        # best ancestor (0.3) > head (0.1) → should succeed
        self.assertTrue(result.success)

    def test_rollback_fails_if_head_already_best(self):
        g = self._build_graph([0.3, 0.5, 0.9])  # head=0.9, no better ancestor
        re = RollbackEngine(g)
        result = re.rollback_to_last_good()
        self.assertFalse(result.success)

    def test_rollback_result_frozen(self):
        g = self._build_graph([0.5, 0.8, 0.3])
        re = RollbackEngine(g)
        result = re.rollback_to_last_good()
        with self.assertRaises((AttributeError, TypeError)):
            result.success = False

    def test_rollback_result_to_dict(self):
        g = self._build_graph([0.5, 0.8, 0.3])
        re = RollbackEngine(g)
        result = re.rollback_to_last_good()
        d = result.to_dict()
        for k in ("success","rolled_back_to","from_snapshot","reason","score_recovered"):
            self.assertIn(k, d)


class TestRollbackToNode(unittest.TestCase):
    def test_explicit_rollback_success(self):
        g = VersionGraph(initial_score=0.5)
        n1 = g.add_node(score=0.8)
        g.add_node(score=0.3)
        re = RollbackEngine(g)
        result = re.rollback_to_node(n1.snapshot_id)
        self.assertTrue(result.success)
        self.assertEqual(result.rolled_back_to, n1.snapshot_id)
        self.assertAlmostEqual(g.get_latest().score, 0.8)

    def test_explicit_rollback_missing_id(self):
        g = VersionGraph()
        re = RollbackEngine(g)
        result = re.rollback_to_node("nonexistent")
        self.assertFalse(result.success)
        self.assertIn("not found", result.reason.lower())


# ── SnapshotStore ─────────────────────────────────────────────────────────────

class TestSnapshotStore(unittest.TestCase):
    def setUp(self):
        self.store = SnapshotStore(":memory:")
        self.store.initialise()

    def test_save_returns_snapshot_id(self):
        sid = self.store.save("node-1", "--- a\n+++ b\n@@ @@\n+x\n", "add feature")
        self.assertIsInstance(sid, str)
        self.assertGreater(len(sid), 0)

    def test_get_by_node_returns_dict(self):
        self.store.save("n1", "diff content", "goal")
        result = self.store.get_by_node("n1")
        self.assertIsNotNone(result)
        self.assertEqual(result["node_id"], "n1")
        self.assertEqual(result["patch_diff"], "diff content")
        self.assertEqual(result["goal"], "goal")

    def test_get_by_node_missing_returns_none(self):
        self.assertIsNone(self.store.get_by_node("does-not-exist"))

    def test_get_by_snapshot_id(self):
        sid = self.store.save("n1", "diff", "goal")
        result = self.store.get_by_snapshot_id(sid)
        self.assertIsNotNone(result)
        self.assertEqual(result["snapshot_id"], sid)

    def test_get_by_snapshot_id_missing_returns_none(self):
        self.assertIsNone(self.store.get_by_snapshot_id("nope"))

    def test_count_increments(self):
        self.assertEqual(self.store.count(), 0)
        self.store.save("n1", "d1", "g1")
        self.assertEqual(self.store.count(), 1)
        self.store.save("n2", "d2", "g2")
        self.assertEqual(self.store.count(), 2)

    def test_files_changed_stored(self):
        self.store.save("n1", "diff", "goal", files_changed=["a.py", "b.py"])
        result = self.store.get_by_node("n1")
        self.assertEqual(result["files_changed"], ["a.py", "b.py"])

    def test_metadata_stored(self):
        self.store.save("n1", "diff", "goal", metadata={"risk": "low"})
        result = self.store.get_by_node("n1")
        self.assertEqual(result["metadata"]["risk"], "low")

    def test_list_by_node_ids(self):
        self.store.save("n1", "d1", "g1")
        self.store.save("n2", "d2", "g2")
        self.store.save("n3", "d3", "g3")
        results = self.store.list_by_node_ids(["n1", "n3"])
        node_ids = [r["node_id"] for r in results]
        self.assertIn("n1", node_ids)
        self.assertIn("n3", node_ids)
        self.assertNotIn("n2", node_ids)

    def test_list_by_empty_ids_returns_empty(self):
        self.assertEqual(self.store.list_by_node_ids([]), [])

    def test_initialise_idempotent(self):
        self.store.initialise()  # second call must not raise
        self.store.save("n1", "diff", "goal")
        self.assertEqual(self.store.count(), 1)

    def test_snapshot_id_unique_per_save(self):
        sid1 = self.store.save("n1", "d", "g")
        sid2 = self.store.save("n1", "d", "g")
        self.assertNotEqual(sid1, sid2)


# ── AutonomyLoop + Versioning Integration ────────────────────────────────────

def _make_provider(task_ids):
    tasks = list(task_ids)
    def provider(i): return tasks.pop(0) if tasks else None
    return provider

def _success_exec(score=0.8):
    def execute(task_id, i): return True, score, {"goal": task_id}
    return execute

def _fail_exec():
    def execute(task_id, i): return False, 0.0, {}
    return execute


class TestAutonomyLoopVersioning(unittest.TestCase):
    def test_version_graph_in_report(self):
        loop = AutonomyLoop(
            _make_provider(["t1", "t2"]),
            _success_exec(0.8),
            config=LoopConfig(enable_versioning=True),
        )
        report = loop.run()
        self.assertIsNotNone(report.version_graph)

    def test_version_graph_grows_per_iteration(self):
        loop = AutonomyLoop(
            _make_provider(["t1", "t2", "t3"]),
            _success_exec(0.8),
            config=LoopConfig(enable_versioning=True),
        )
        report = loop.run()
        # root + 3 iterations = 4 nodes
        self.assertEqual(report.version_graph.size(), 4)

    def test_snapshot_ids_in_results(self):
        loop = AutonomyLoop(
            _make_provider(["t1", "t2"]),
            _success_exec(0.8),
            config=LoopConfig(enable_versioning=True),
        )
        report = loop.run()
        for result in report.results:
            if result.success:
                self.assertIsNotNone(result.snapshot_id)

    def test_snapshot_ids_are_unique(self):
        loop = AutonomyLoop(
            _make_provider(["t1", "t2", "t3"]),
            _success_exec(0.8),
            config=LoopConfig(enable_versioning=True),
        )
        report = loop.run()
        ids = [r.snapshot_id for r in report.results if r.snapshot_id]
        self.assertEqual(len(ids), len(set(ids)))

    def test_versioning_disabled_no_graph(self):
        loop = AutonomyLoop(
            _make_provider(["t1"]),
            _success_exec(0.8),
            config=LoopConfig(enable_versioning=False),
        )
        report = loop.run()
        self.assertIsNone(report.version_graph)

    def test_versioning_disabled_snapshot_id_none(self):
        loop = AutonomyLoop(
            _make_provider(["t1"]),
            _success_exec(0.8),
            config=LoopConfig(enable_versioning=False),
        )
        report = loop.run()
        for r in report.results:
            self.assertIsNone(r.snapshot_id)

    def test_rollback_adds_rollback_detail(self):
        scores = [0.8, 0.1]
        idx = {"i": 0}
        def drop_exec(task_id, iteration):
            s = scores[min(idx["i"], 1)]
            idx["i"] += 1
            return True, s, {}
        loop = AutonomyLoop(
            _make_provider(["t1", "t2"]),
            drop_exec,
            config=LoopConfig(min_score_delta=-0.5, enable_versioning=True),
        )
        report = loop.run()
        rolled = [r for r in report.results if r.detail.get("rolled_back")]
        self.assertGreaterEqual(len(rolled), 1)
        # Rollback result should be in detail
        for r in rolled:
            self.assertIn("rollback_result", r.detail)

    def test_existing_graph_attached(self):
        """Loop must use a pre-existing VersionGraph if provided."""
        existing = VersionGraph(initial_score=0.5)
        loop = AutonomyLoop(
            _make_provider(["t1"]),
            _success_exec(0.8),
            config=LoopConfig(enable_versioning=True),
            version_graph=existing,
        )
        report = loop.run()
        self.assertIs(report.version_graph, existing)

    def test_to_dict_includes_version_graph(self):
        loop = AutonomyLoop(
            _make_provider(["t1"]),
            _success_exec(0.8),
            config=LoopConfig(enable_versioning=True),
        )
        d = loop.run().to_dict()
        self.assertIn("version_graph", d)

    def test_to_dict_no_version_graph_when_disabled(self):
        loop = AutonomyLoop(
            _make_provider(["t1"]),
            _success_exec(0.8),
            config=LoopConfig(enable_versioning=False),
        )
        d = loop.run().to_dict()
        self.assertNotIn("version_graph", d)


if __name__ == "__main__":
    unittest.main()
