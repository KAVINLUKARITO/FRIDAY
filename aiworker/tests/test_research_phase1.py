import json
import unittest

from aiworker.research.clustering import ClusteringEngine
from aiworker.research.extraction import ExtractionEngine, StubBackend
from aiworker.research.models import (
    KnowledgeCluster,
    ResearchGoal,
    ResearchReport,
    SourceMetadata,
)
from aiworker.research.scraper import ScraperEngine
from aiworker.research.search import SearchEngine
from aiworker.research.progress import research_progress, get_research_progress, get_research_status
from aiworker.research.validation import ValidationEngine, compute_coverage_score
from aiworker.research.controller import ResearchController

_STUB_JSON: str = json.dumps({
    "summary": "A document about a topic.",
    "key_concepts": ["shared concept"],
    "code_snippets": ["print('hello')"],
    "claims": ["This approach is effective.", "Performance is acceptable."],
    "risks": ["May not scale."],
})

_VALID_CLUSTER: KnowledgeCluster = KnowledgeCluster(
    consensus_points=("Point A.", "Point B.", "Point C.", "Point D.", "Point E."),
    conflicting_points=(),
    implementation_steps=("Step 1.",),
    confidence_score=0.8,
)


def _make_report(
    num_domains: int = 50,
    source_types: tuple[str, ...] = ("blog", "paper", "documentation"),
    clusters: tuple[KnowledgeCluster, ...] = (_VALID_CLUSTER,),
    coverage_score: float = 0.7,
) -> ResearchReport:
    goal: ResearchGoal = ResearchGoal(topic="test", depth=1, max_sources=num_domains)
    domains: tuple[str, ...] = tuple(f"domain{i:03d}.com" for i in range(num_domains))
    sources: tuple[SourceMetadata, ...] = tuple(
        SourceMetadata(
            url=f"https://{d}/article",
            domain=d,
            source_type=source_types[i % len(source_types)],
            authority_score=0.5,
        )
        for i, d in enumerate(domains)
    )
    return ResearchReport(
        goal=goal,
        sources=sources,
        documents=(),
        total_sources=num_domains,
        unique_domains=domains,
        source_types=source_types,
        clusters=clusters,
        coverage_score=coverage_score,
    )


class TestEndToEnd(unittest.TestCase):

    def setUp(self) -> None:
        research_progress.reset()

    def test_end_to_end_success(self) -> None:
        backend: StubBackend = StubBackend(_STUB_JSON)
        controller: ResearchController = ResearchController(
            search_engine=SearchEngine(),
            scraper_engine=ScraperEngine(),
            extraction_engine=ExtractionEngine(backend),
            clustering_engine=ClusteringEngine(),
            validation_engine=ValidationEngine(),
        )
        goal: ResearchGoal = ResearchGoal(topic="testing", depth=2, max_sources=50)
        report: ResearchReport = controller.run(goal)
        self.assertIsInstance(report, ResearchReport)
        self.assertGreaterEqual(report.coverage_score, 0.5)
        self.assertGreaterEqual(len(report.unique_domains), 50)
        self.assertGreaterEqual(len(set(report.source_types)), 3)

    def test_research_progress_reaches_completion(self) -> None:
        controller: ResearchController = ResearchController(
            search_engine=SearchEngine(),
            scraper_engine=ScraperEngine(),
        )
        goal: ResearchGoal = ResearchGoal(topic="testing", depth=1, max_sources=50)

        report: ResearchReport = controller.run(goal)
        status = get_research_status()

        self.assertEqual(len(report.sources), 50)
        self.assertEqual(status["research_tasks_total"], 50)
        self.assertEqual(status["research_tasks_completed"], 50)
        self.assertEqual(get_research_progress(), 1.0)


class TestValidationFailures(unittest.TestCase):

    def setUp(self) -> None:
        self.engine: ValidationEngine = ValidationEngine()

    def test_fail_less_than_50_domains(self) -> None:
        report: ResearchReport = _make_report(num_domains=10)
        self.assertFalse(self.engine.validate(report))

    def test_fail_low_confidence_cluster(self) -> None:
        bad_cluster: KnowledgeCluster = KnowledgeCluster(
            consensus_points=("A.",),
            conflicting_points=(),
            implementation_steps=(),
            confidence_score=0.1,
        )
        report: ResearchReport = _make_report(clusters=(bad_cluster,))
        self.assertFalse(self.engine.validate(report))

    def test_fail_low_coverage_score(self) -> None:
        report: ResearchReport = _make_report(coverage_score=0.2)
        self.assertFalse(self.engine.validate(report))


class TestCoverageScore(unittest.TestCase):

    def test_coverage_score_bounds(self) -> None:
        for n_domains in (50, 100):
            for n_types in (3, 5):
                types: tuple[str, ...] = tuple(
                    f"type{i}" for i in range(n_types)
                )
                report: ResearchReport = _make_report(
                    num_domains=n_domains,
                    source_types=types,
                    clusters=(_VALID_CLUSTER,),
                    coverage_score=0.0,
                )
                score: float = compute_coverage_score(report)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 1.0)

    def test_deterministic_coverage(self) -> None:
        report: ResearchReport = _make_report(coverage_score=0.0)
        first: float = compute_coverage_score(report)
        second: float = compute_coverage_score(report)
        self.assertEqual(first, second)


class TestNoSideEffects(unittest.TestCase):

    def test_no_side_effects(self) -> None:
        report: ResearchReport = _make_report()
        original_score: float = report.coverage_score
        original_domains: tuple[str, ...] = report.unique_domains
        engine: ValidationEngine = ValidationEngine()
        engine.validate(report)
        self.assertEqual(report.coverage_score, original_score)
        self.assertEqual(report.unique_domains, original_domains)


if __name__ == "__main__":
    unittest.main()
