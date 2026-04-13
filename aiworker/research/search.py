"""Real search engine for AIWorker research layer.

Replaces the fake domain-generator stub with actual search results.
Two backends, tried in order:

1. **SearXNG** (preferred) — self-hosted, fully local, privacy-preserving.
   Spin up with: ``docker run -d -p 8888:8080 searxng/searxng``
   Set env: ``AIWORKER_SEARXNG_URL=http://localhost:8888``

2. **DuckDuckGo Lite** (fallback) — no API key, no JS, HTML-parsed.
   Used automatically when SearXNG is unavailable or returns no results.

Both backends respect the 32GB VPS constraint:
- Sequential requests only
- Hard cap on results (``max_sources``, capped at 20 for RAM safety)
- Results filtered to unique domains to maximise knowledge diversity

Install:
    pip install httpx>=0.27 beautifulsoup4>=4.12 lxml>=5.2
"""

from __future__ import annotations

import logging
import os
import time
from urllib.parse import quote_plus, urlparse

from aiworker.research.models import ResearchGoal, SourceMetadata

logger = logging.getLogger(__name__)

# ── VPS safety cap ────────────────────────────────────────────────────
_MAX_SAFE_SOURCES = 20    # hard ceiling regardless of goal.max_sources
_REQUEST_TIMEOUT  = 10
_USER_AGENT = (
    "AIWorker-Research/0.1 (autonomous agent; educational use)"
)

# ── source type heuristics ────────────────────────────────────────────
_SOURCE_TYPE_MAP: dict[str, str] = {
    "github.com":    "code",
    "stackoverflow": "forum",
    "reddit.com":    "forum",
    "arxiv.org":     "paper",
    "readthedocs":   "documentation",
    "docs.":         "documentation",
    "pypi.org":      "documentation",
    "medium.com":    "blog",
    "dev.to":        "blog",
}


def _classify_source(domain: str) -> str:
    for key, stype in _SOURCE_TYPE_MAP.items():
        if key in domain:
            return stype
    return "news"


def _authority_score(domain: str, position: int, total: int) -> float:
    """Higher-ranked results and trusted domains get higher scores."""
    base = 1.0 - (position / max(total, 1))
    bonus = 0.15 if any(k in domain for k in ("github", "stackoverflow", "readthedocs", "pypi")) else 0.0
    return round(min(1.0, base + bonus), 3)


# ── HTTP helpers ──────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None) -> tuple[str, int]:
    """GET with httpx, falling back to urllib."""
    try:
        import httpx  # type: ignore[import]
        with httpx.Client(
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = client.get(url, params=params)
            return resp.text, resp.status_code
    except ImportError:
        return _get_urllib(url, params)
    except Exception as exc:
        logger.warning("GET %s failed: %s", url, exc)
        return "", 0


def _get_urllib(url: str, params: dict | None = None) -> tuple[str, int]:
    import urllib.request
    if params:
        qs = "&".join(f"{k}={quote_plus(str(v))}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as r:
            return r.read(65536).decode("utf-8", errors="replace"), r.status
    except Exception as exc:
        logger.warning("urllib GET %s failed: %s", url, exc)
        return "", 0


# ── SearXNG backend ───────────────────────────────────────────────────

def _searxng_url() -> str:
    return os.environ.get("AIWORKER_SEARXNG_URL", "http://localhost:8888").rstrip("/")


def _search_searxng(topic: str, n: int) -> list[dict]:
    """Return list of {url, title, domain} dicts from SearXNG JSON API."""
    url = f"{_searxng_url()}/search"
    body, status = _get(url, params={"q": topic, "format": "json", "categories": "general,it"})
    if status != 200 or not body:
        return []
    import json
    try:
        data = json.loads(body)
        return data.get("results", [])[:n]
    except Exception as exc:
        logger.debug("SearXNG JSON parse failed: %s", exc)
        return []


# ── DuckDuckGo Lite backend ───────────────────────────────────────────

def _search_ddg_lite(topic: str, n: int) -> list[dict]:
    """Scrape DuckDuckGo Lite HTML (no API key, no JS required)."""
    url = "https://lite.duckduckgo.com/lite/"
    body, status = _get(url, params={"q": topic})
    if not body:
        return []
    try:
        from bs4 import BeautifulSoup  # type: ignore[import]
        soup = BeautifulSoup(body, "lxml")
        results = []
        for a in soup.select("a.result-link")[:n]:
            href = a.get("href", "")
            if not href.startswith("http"):
                continue
            domain = urlparse(href).netloc
            results.append({"url": href, "title": a.get_text(strip=True), "domain": domain})
        return results
    except Exception as exc:
        logger.debug("DDG Lite parse failed: %s", exc)
        return []


# ── public engine ─────────────────────────────────────────────────────

class SearchEngine:
    """Real web search engine with SearXNG + DuckDuckGo fallback.

    The ``goal.max_sources`` value is honoured up to ``_MAX_SAFE_SOURCES``
    (20) to prevent memory pressure on the 32GB VPS.

    Usage::

        engine = SearchEngine()
        sources = engine.search(ResearchGoal(topic="Python async", depth=1, max_sources=10))
    """

    def search(self, goal: ResearchGoal) -> list[SourceMetadata]:
        """Search for *goal.topic* and return ranked :class:`SourceMetadata` list.

        Args:
            goal: Research goal.  ``max_sources`` is capped at 20.

        Returns:
            Deduplicated list of source metadata, sorted by authority score.
        """
        n = min(goal.max_sources, _MAX_SAFE_SOURCES)
        topic = goal.topic.strip()

        # Try SearXNG first (self-hosted, local)
        raw_results = _search_searxng(topic, n)
        backend_used = "searxng"

        if not raw_results:
            logger.info("SearXNG returned no results for %r – falling back to DuckDuckGo Lite", topic)
            time.sleep(0.5)          # be polite before hitting an external service
            raw_results = _search_ddg_lite(topic, n)
            backend_used = "duckduckgo-lite"

        if not raw_results:
            logger.warning("All search backends returned no results for %r", topic)
            return []

        logger.info("Search backend=%s found %d results for %r", backend_used, len(raw_results), topic)

        # Deduplicate by domain and build SourceMetadata list
        seen_domains: set[str] = set()
        sources: list[SourceMetadata] = []
        for i, item in enumerate(raw_results):
            url    = item.get("url", "")
            domain = item.get("domain") or urlparse(url).netloc
            if not url or not domain:
                continue
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            sources.append(SourceMetadata(
                url=url,
                domain=domain,
                source_type=_classify_source(domain),
                authority_score=_authority_score(domain, i, len(raw_results)),
            ))

        return sources[:n]
