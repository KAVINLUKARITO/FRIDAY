"""Safe retrieval fetcher — Phase 3.

Fetches content from allowlisted domains only.
Falls back gracefully on any error. Never raises to caller.
Network access is optional — if disabled, returns a blocked result.
"""
from __future__ import annotations
import urllib.request
import urllib.error
from typing import Optional

from aiworker.retrieval.allowlist import DEFAULT_ALLOWED_DOMAINS, is_allowed
from aiworker.retrieval.models import RetrievalRequest, RetrievalResult, RetrievalStatus

# Global kill switch — set to False to disable all network access
NETWORK_ENABLED: bool = False
_MAX_CONTENT_BYTES: int = 8192


def fetch(request: RetrievalRequest) -> RetrievalResult:
    """Perform a sandboxed retrieval for the given request.

    Safety properties:
    - Always checks allowlist before any network call
    - Caps content at _MAX_CONTENT_BYTES
    - Falls back on any network / parse error
    - Returns BLOCKED if NETWORK_ENABLED is False

    Args:
        request: A :class:`RetrievalRequest`.

    Returns:
        A :class:`RetrievalResult` — never raises.
    """
    if not NETWORK_ENABLED:
        return RetrievalResult(
            status=RetrievalStatus.BLOCKED,
            query=request.query,
            content="",
            source_url="",
            blocked_reason="Network access is disabled (NETWORK_ENABLED=False)",
        )

    allowed_set = frozenset(request.allowed_domains) or DEFAULT_ALLOWED_DOMAINS
    url = _build_url(request.query, allowed_set)

    if url is None:
        return RetrievalResult(
            status=RetrievalStatus.BLOCKED,
            query=request.query,
            content="",
            source_url="",
            blocked_reason="No valid URL could be constructed for query",
        )

    ok, reason = is_allowed(url, allowed_set)
    if not ok:
        return RetrievalResult(
            status=RetrievalStatus.BLOCKED,
            query=request.query,
            content="",
            source_url=url,
            blocked_reason=reason,
        )

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AIWorker/1.0 (documentation fetcher)"},
        )
        with urllib.request.urlopen(req, timeout=request.timeout_seconds) as resp:
            raw = resp.read(_MAX_CONTENT_BYTES)
            content = raw.decode("utf-8", errors="replace")
        return RetrievalResult(
            status=RetrievalStatus.SUCCESS,
            query=request.query,
            content=content,
            source_url=url,
        )
    except urllib.error.URLError as exc:
        return RetrievalResult(
            status=RetrievalStatus.TIMEOUT,
            query=request.query,
            content="",
            source_url=url,
            blocked_reason=str(exc),
        )
    except Exception as exc:
        return RetrievalResult(
            status=RetrievalStatus.ERROR,
            query=request.query,
            content="",
            source_url=url,
            blocked_reason=str(exc),
        )


def _build_url(query: str, allowed_domains: frozenset[str]) -> Optional[str]:
    """Build a documentation search URL from query + first allowed domain."""
    if not allowed_domains:
        return None
    domain = sorted(allowed_domains)[0]
    # Simple: search docs.python.org
    encoded = urllib.parse.quote_plus(query) if hasattr(urllib, "parse") else query.replace(" ", "+")
    return f"https://{domain}/3/search.html?q={encoded}"


# Fix missing import
import urllib.parse  # noqa: E402
