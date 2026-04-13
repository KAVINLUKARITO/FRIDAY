"""Tests for Phase 3 — Safe Retrieval Layer (unittest)."""
from __future__ import annotations
import unittest
from unittest.mock import patch, MagicMock

from aiworker.retrieval.allowlist import is_allowed, DEFAULT_ALLOWED_DOMAINS
from aiworker.retrieval.models import RetrievalRequest, RetrievalStatus
from aiworker.retrieval import fetcher
from aiworker.retrieval.fetcher import fetch


class TestAllowlist(unittest.TestCase):
    def test_allowed_domain_passes(self):
        ok, _ = is_allowed("https://docs.python.org/3/", DEFAULT_ALLOWED_DOMAINS)
        self.assertTrue(ok)

    def test_http_rejected(self):
        ok, reason = is_allowed("http://docs.python.org/", DEFAULT_ALLOWED_DOMAINS)
        self.assertFalse(ok)
        self.assertIn("HTTPS", reason)

    def test_unknown_domain_rejected(self):
        ok, reason = is_allowed("https://evil.com/hack", DEFAULT_ALLOWED_DOMAINS)
        self.assertFalse(ok)

    def test_localhost_blocked(self):
        ok, _ = is_allowed("https://localhost/api", DEFAULT_ALLOWED_DOMAINS)
        self.assertFalse(ok)

    def test_packaging_python_org_allowed(self):
        ok, _ = is_allowed("https://packaging.python.org/en/latest/", DEFAULT_ALLOWED_DOMAINS)
        self.assertTrue(ok)

    def test_empty_allowed_set_rejects_all(self):
        ok, _ = is_allowed("https://docs.python.org/", frozenset())
        self.assertFalse(ok)


class TestFetcherNetworkDisabled(unittest.TestCase):
    def test_blocked_when_network_disabled(self):
        req = RetrievalRequest(query="generators", allowed_domains=("docs.python.org",))
        result = fetch(req)
        self.assertEqual(result.status, RetrievalStatus.BLOCKED)
        self.assertIn("NETWORK_ENABLED", result.blocked_reason or "")

    def test_query_preserved(self):
        req = RetrievalRequest(query="type hints")
        result = fetch(req)
        self.assertEqual(result.query, "type hints")

    def test_frozen_result(self):
        req = RetrievalRequest(query="test")
        result = fetch(req)
        with self.assertRaises((AttributeError, TypeError)):
            result.status = RetrievalStatus.SUCCESS

    def test_to_dict_structure(self):
        result = fetch(RetrievalRequest(query="pytest"))
        d = result.to_dict()
        for k in ("status","query","blocked_reason"):
            self.assertIn(k, d)


class TestFetcherNetworkEnabled(unittest.TestCase):
    def test_successful_mock_fetch(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html>Python docs</html>"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch.object(fetcher, "NETWORK_ENABLED", True):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                req = RetrievalRequest(query="generators", allowed_domains=("docs.python.org",))
                result = fetch(req)
        self.assertEqual(result.status, RetrievalStatus.SUCCESS)
        self.assertIn("Python docs", result.content)

    def test_url_error_returns_timeout_or_error(self):
        import urllib.error
        with patch.object(fetcher, "NETWORK_ENABLED", True):
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
                req = RetrievalRequest(query="generators", allowed_domains=("docs.python.org",))
                result = fetch(req)
        self.assertIn(result.status, (RetrievalStatus.TIMEOUT, RetrievalStatus.ERROR))


class TestRetrievalRequest(unittest.TestCase):
    def test_default_max_results(self):
        self.assertEqual(RetrievalRequest(query="test").max_results, 3)

    def test_default_timeout(self):
        self.assertEqual(RetrievalRequest(query="test").timeout_seconds, 10.0)

    def test_frozen(self):
        req = RetrievalRequest(query="test")
        with self.assertRaises((AttributeError, TypeError)):
            req.query = "changed"


if __name__ == "__main__":
    unittest.main()
