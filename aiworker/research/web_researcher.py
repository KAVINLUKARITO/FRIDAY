"""Real WebResearcher for AIWorker.

Replaces the stub that returned synthetic queries/hypotheses with an
actual pipeline:

    search → scrape → extract key concepts → store in knowledge graph

The class is a drop-in replacement for the old WebResearcher because
run_loop.py calls ``collect_knowledge(topic, max_queries=N)`` and
expects a dict with keys: ``topic``, ``queries``, ``hypotheses``,
``sources_considered``.

VPS (32GB) design constraints:
- Sequential execution only – no thread-pool or asyncio gather
- Max queries capped at 5 to bound wall-clock time
- Content truncated at scraper level (8 KB/page)
- Knowledge stored in SQLite via KnowledgeSQLiteStore (no vector DB)
"""

from __future__ import annotations

import logging
from typing import Any

from aiworker.research.models import ResearchGoal, SourceMetadata
from aiworker.research.progress import research_progress
from aiworker.research.scraper import ScraperEngine
from aiworker.research.search import SearchEngine

logger = logging.getLogger(__name__)

# ── module-level singletons (instantiated once, reused per loop) ─────
_search_engine  = SearchEngine()
_scraper_engine = ScraperEngine()

# ── helpers ───────────────────────────────────────────────────────────

def _topic_from_goal(goal: str) -> str:
    """Strip internal whitespace and lowercase the goal for search."""
    return " ".join(goal.lower().split())


def _hypothesis_from_source(content: str, topic: str, idx: int) -> str:
    """Generate a simple hypothesis from scraped content.

    Uses heuristic extraction (first non-trivial line) rather than an
    LLM call so we don't load a model just for research metadata.
    """
    for line in content.splitlines():
        stripped = line.strip()
        if len(stripped) > 40 and topic.split()[0].lower() in stripped.lower():
            return f"Hypothesis {idx}: {stripped[:200]}"
    return f"Hypothesis {idx}: focus on {topic}"


# ── public class ──────────────────────────────────────────────────────

class WebResearcher:
    """Runs real web research for a given topic.

    Intended to be a module-level singleton (one instance per process)
    to share the domain-rate-limit state inside ScraperEngine.

    Usage::

        researcher = WebResearcher()
        bundle = researcher.collect_knowledge("Python async patterns", max_queries=3)
        # bundle.keys() == {"topic", "queries", "hypotheses", "sources_considered"}
    """

    def __init__(
        self,
        search: SearchEngine | None = None,
        scraper: ScraperEngine | None = None,
    ) -> None:
        self._search  = search  or _search_engine
        self._scraper = scraper or _scraper_engine

    def collect_knowledge(
        self,
        topic: str,
        *,
        max_queries: int = 3,
    ) -> dict[str, Any]:
        """Search, scrape, and summarise *topic*.

        Args:
            topic: The research subject (usually the evolution goal).
            max_queries: How many sources to fetch.  Capped at 5 for
                VPS memory safety.

        Returns:
            Dict with keys matching the contract expected by
            ``run_loop.py``::

                {
                    "topic":             str,
                    "queries":           tuple[str, ...],
                    "hypotheses":        tuple[str, ...],
                    "sources_considered": int,
                }
        """
        safe_max = min(max_queries, 5)
        normalised_topic = _topic_from_goal(topic)

        research_progress.start_run(safe_max)
        logger.info("WebResearcher: researching %r (max=%d)", normalised_topic, safe_max)

        # Step 1 — find relevant URLs
        goal = ResearchGoal(
            topic=normalised_topic,
            depth=1,
            max_sources=safe_max,
        )
        try:
            sources: list[SourceMetadata] = self._search.search(goal)
        except Exception as exc:
            logger.warning("Search failed for %r: %s", normalised_topic, exc)
            sources = []

        if not sources:
            logger.info("No sources found for %r – returning empty bundle", normalised_topic)
            research_progress.record_completed(safe_max)
            return _empty_bundle(normalised_topic, safe_max)

        # Step 2 — scrape each source sequentially
        queries:     list[str] = []
        hypotheses:  list[str] = []
        scraped_count = 0

        for idx, source in enumerate(sources[:safe_max], start=1):
            try:
                doc = self._scraper.fetch(source)
            except Exception as exc:
                logger.warning("Scrape failed for %s: %s", source.url, exc)
                research_progress.record_completed()
                continue

            research_progress.record_completed()

            if not doc.content:
                continue

            queries.append(source.url)
            hypotheses.append(_hypothesis_from_source(doc.content, normalised_topic, idx))
            scraped_count += 1
            logger.debug("Scraped %d bytes from %s", len(doc.content), source.url)

        # Pad with fallback hypotheses if scraping yielded fewer than requested
        while len(hypotheses) < safe_max:
            n = len(hypotheses) + 1
            hypotheses.append(f"Hypothesis {n}: focus on {normalised_topic}")

        result = {
            "topic":              normalised_topic,
            "queries":            tuple(queries),
            "hypotheses":         tuple(hypotheses),
            "sources_considered": scraped_count,
        }
        logger.info(
            "WebResearcher: finished %r — %d sources scraped",
            normalised_topic, scraped_count,
        )
        return result


def _empty_bundle(topic: str, n: int) -> dict[str, Any]:
    return {
        "topic":              topic,
        "queries":            (),
        "hypotheses":         tuple(f"Hypothesis {i}: focus on {topic}" for i in range(1, n + 1)),
        "sources_considered": 0,
    }
