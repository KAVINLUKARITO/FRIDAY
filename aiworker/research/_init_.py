"""
Research subsystem (Phase 1).

Deterministic research pipeline:
search → scrape → report (placeholder).
"""

from .models import (
    ResearchGoal,
    SourceMetadata,
    RawDocument,
    ExtractedKnowledge,
    KnowledgeCluster,
    ResearchReport,
)

from .search import SearchEngine
from .scraper import ScraperEngine
from .controller import ResearchController
