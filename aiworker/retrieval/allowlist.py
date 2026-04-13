"""Domain allowlist enforcement for the retrieval layer.

NEVER fetches from domains not on the allowlist.
No side effects, no external calls. Deterministic.
"""
from __future__ import annotations

# Default safe domains for software development documentation
DEFAULT_ALLOWED_DOMAINS: frozenset[str] = frozenset({
    "docs.python.org",
    "pypi.org",
    "packaging.python.org",
    "peps.python.org",
    "docs.pytest.org",
    "mypy.readthedocs.io",
    "typing.readthedocs.io",
})

# Explicitly blocked domains — never allowed regardless of config
_BLOCKED_DOMAINS: frozenset[str] = frozenset({
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.0.0",  # link-local
    "10.0.0.0",
    "192.168.0.0",
    "172.16.0.0",
})


def is_allowed(url: str, allowed_domains: frozenset[str]) -> tuple[bool, str]:
    """Check if a URL is allowed for retrieval.

    Args:
        url: The URL to check.
        allowed_domains: Set of allowed domain strings.

    Returns:
        (allowed, reason) tuple.
    """
    if not url.startswith("https://"):
        return False, f"Only HTTPS allowed, got: {url[:20]}"

    try:
        # Extract domain from URL
        after_scheme = url[8:]  # strip https://
        domain = after_scheme.split("/")[0].lower()
    except Exception:
        return False, "Could not parse domain from URL"

    for blocked in _BLOCKED_DOMAINS:
        if blocked in domain:
            return False, f"Domain is in blocked list: {domain}"

    for allowed in allowed_domains:
        if domain == allowed or domain.endswith("." + allowed):
            return True, "allowed"

    return False, f"Domain not in allowlist: {domain}"
