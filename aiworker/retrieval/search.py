from __future__ import annotations

import re

import requests

_DDG_HTML_ENDPOINT = "https://duckduckgo.com/html/"


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def search_web(query: str, max_results: int = 5) -> list[str]:
    if not query.strip() or max_results <= 0:
        return []

    try:
        response = requests.get(
            _DDG_HTML_ENDPOINT,
            params={"q": query},
            timeout=10,
            headers={"User-Agent": "aiworker/1.0"},
        )
        response.raise_for_status()
        html = response.text

        title_matches = re.findall(
            r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        snippet_matches = re.findall(
            r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        items: list[str] = []
        total_chars = 0
        for idx, title_html in enumerate(title_matches[:max_results]):
            title = _strip_html(title_html)
            snippet = _strip_html(snippet_matches[idx]) if idx < len(snippet_matches) else ""
            if not title and not snippet:
                continue
            line = f"{title}: {snippet}" if snippet else title
            if total_chars + len(line) > 2000:
                break
            items.append(line)
            total_chars += len(line)

        return items
    except Exception:
        return []
