"""Real HTTP scraper for AIWorker research layer.

Replaces the previous deterministic placeholder with actual network
fetching via httpx + BeautifulSoup.  Designed for a 32GB VPS:

- Single synchronous request per call (no parallelism)
- Hard content cap (8 KB) to bound memory
- Domain-based rate limiting via a simple in-process token bucket
- Graceful fallback to empty RawDocument on any network error
- No third-party dependencies beyond httpx and beautifulsoup4

Install:
    pip install httpx>=0.27 beautifulsoup4>=4.12 lxml>=5.2
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from aiworker.research.models import RawDocument, SourceMetadata

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────
_MAX_CONTENT_BYTES = 8_192           # 8 KB per page – keeps RAM usage flat
_REQUEST_TIMEOUT   = 12              # seconds per request
_MIN_GAP_SECONDS   = 1.5            # politeness: minimum gap between requests to same domain
_USER_AGENT        = (
    "AIWorker-Research/0.1 (autonomous agent; educational use; "
    "contact: <configure AIWORKER_CONTACT_EMAIL>)"
)

# ── per-domain rate limiting ─────────────────────────────────────────
_last_fetch: dict[str, float] = {}


def _polite_wait(domain: str) -> None:
    """Block until the minimum inter-request gap for *domain* has elapsed."""
    last = _last_fetch.get(domain, 0.0)
    gap  = time.monotonic() - last
    if gap < _MIN_GAP_SECONDS:
        time.sleep(_MIN_GAP_SECONDS - gap)
    _last_fetch[domain] = time.monotonic()


def _extract_text(html: str) -> str:
    """Extract readable text from HTML, falling back to raw slice on error."""
    try:
        from bs4 import BeautifulSoup  # type: ignore[import]
        soup = BeautifulSoup(html, "lxml")
        # Remove noise nodes
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Collapse excessive blank lines
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines)
    except Exception as exc:
        logger.debug("BeautifulSoup parse failed (%s) – using raw slice", exc)
        return html[:_MAX_CONTENT_BYTES]


def _fetch_url(url: str) -> tuple[str, int]:
    """Return (body_text, status_code).  Never raises."""
    try:
        import httpx  # type: ignore[import]
        with httpx.Client(
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            response = client.get(url)
            return response.text, response.status_code
    except ImportError:
        logger.warning("httpx not installed – falling back to urllib")
        return _fetch_url_urllib(url)
    except Exception as exc:
        logger.warning("Fetch failed for %s: %s", url, exc)
        return "", 0


def _fetch_url_urllib(url: str) -> tuple[str, int]:
    """Pure-stdlib fallback when httpx is unavailable."""
    import urllib.request
    import urllib.error
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            charset = resp.headers.get_content_charset("utf-8") or "utf-8"
            return resp.read(_MAX_CONTENT_BYTES * 4).decode(charset, errors="replace"), resp.status
    except Exception as exc:
        logger.warning("urllib fetch failed for %s: %s", url, exc)
        return "", 0


class ScraperEngine:
    """Fetches and cleans web pages for the research pipeline.

    Usage::

        engine = ScraperEngine()
        doc = engine.fetch(source_metadata)

    The engine is stateless between calls except for the module-level
    per-domain rate-limit table.
    """

    def fetch(self, metadata: SourceMetadata) -> RawDocument:
        """Fetch *metadata.url* and return a cleaned :class:`RawDocument`.

        On any network or parsing error, returns a RawDocument with
        empty content so the pipeline can continue without crashing.

        Args:
            metadata: Source to fetch.  Only *url* and *domain* are used.

        Returns:
            A :class:`RawDocument` with text content capped at
            ``_MAX_CONTENT_BYTES`` characters.
        """
        domain = metadata.domain or _domain_from_url(metadata.url)
        _polite_wait(domain)

        raw_html, status = _fetch_url(metadata.url)
        fetched_at = datetime.now(timezone.utc)

        if not raw_html or status == 0:
            logger.info("Empty response for %s (status=%s)", metadata.url, status)
            return RawDocument(
                url=metadata.url,
                domain=domain,
                content="",
                fetched_at=fetched_at,
            )

        if status >= 400:
            logger.info("HTTP %s for %s", status, metadata.url)
            return RawDocument(
                url=metadata.url,
                domain=domain,
                content="",
                fetched_at=fetched_at,
            )

        text = _extract_text(raw_html)
        content = text[:_MAX_CONTENT_BYTES]

        logger.debug(
            "Fetched %s bytes from %s (status=%s)",
            len(content), metadata.url, status,
        )
        return RawDocument(
            url=metadata.url,
            domain=domain,
            content=content,
            fetched_at=fetched_at,
        )


def _domain_from_url(url: str) -> str:
    """Extract the domain from a URL, returning '' on parse failure."""
    try:
        return urlparse(url).netloc or ""
    except Exception:
        return ""
