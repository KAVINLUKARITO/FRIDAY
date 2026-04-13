from typing import Optional

from aiworker.research.clustering import ClusteringEngine
from aiworker.research.extraction import ExtractionEngine
from aiworker.research.models import (
    ExtractedKnowledge,
    KnowledgeCluster,
    RawDocument,
    ResearchGoal,
    ResearchReport,
    SourceMetadata,
)
from aiworker.research.progress import research_progress
from aiworker.research.scraper import ScraperEngine
from aiworker.research.search import SearchEngine
from aiworker.research.validation import ValidationEngine, compute_coverage_score


class ResearchController:

    def __init__(
        self,
        search_engine: SearchEngine,
        scraper_engine: ScraperEngine,
        extraction_engine: Optional[ExtractionEngine] = None,
        clustering_engine: Optional[ClusteringEngine] = None,
        validation_engine: Optional[ValidationEngine] = None,
    ) -> None:
        self._search_engine: SearchEngine = search_engine
        self._scraper_engine: ScraperEngine = scraper_engine
        self._extraction_engine: Optional[ExtractionEngine] = extraction_engine
        self._clustering_engine: Optional[ClusteringEngine] = clustering_engine
        self._validation_engine: Optional[ValidationEngine] = validation_engine

    def run(self, goal: ResearchGoal) -> ResearchReport:
        research_progress.start_run(goal.max_sources)
        sources: list[SourceMetadata] = self._search_engine.search(goal)
        research_progress.set_total(len(sources))

        documents: list[RawDocument] = []
        for source in sources:
            documents.append(self._scraper_engine.fetch(source))
            research_progress.record_completed()

        if (
            self._extraction_engine is None
            or self._clustering_engine is None
            or self._validation_engine is None
        ):
            return ResearchReport(
                goal=goal,
                sources=tuple(sources),
                documents=tuple(documents),
            )

        extracted: list[ExtractedKnowledge] = [
            self._extraction_engine.extract(doc) for doc in documents
        ]

        clusters: list[KnowledgeCluster] = self._clustering_engine.synthesize(
            extracted
        )

        unique_domains: tuple[str, ...] = tuple(
            sorted({s.domain for s in sources})
        )
        source_types: tuple[str, ...] = tuple(
            sorted({s.source_type for s in sources})
        )

        report: ResearchReport = ResearchReport(
            goal=goal,
            sources=tuple(sources),
            documents=tuple(documents),
            total_sources=len(sources),
            unique_domains=unique_domains,
            source_types=source_types,
            clusters=tuple(clusters),
            coverage_score=0.0,
        )

        coverage: float = compute_coverage_score(report)

        report = ResearchReport(
            goal=report.goal,
            sources=report.sources,
            documents=report.documents,
            total_sources=report.total_sources,
            unique_domains=report.unique_domains,
            source_types=report.source_types,
            clusters=report.clusters,
            coverage_score=coverage,
        )

        if not self._validation_engine.validate(report):
            raise ValueError("Research quality threshold not met")

        return report
