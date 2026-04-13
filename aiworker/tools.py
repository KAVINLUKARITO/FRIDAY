from __future__ import annotations

import csv
import hashlib
import json
import random
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup

from config import settings
from logger import get_logger

logger = get_logger("tools")


class SafetyError(Exception):
    """Raised when an operation violates workspace or network safety rules."""


class ToolError(Exception):
    """Raised when a tool fails to complete its work."""


_SECURITY_HEADERS = [
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Content-Security-Policy",
    "Strict-Transport-Security",
    "X-XSS-Protection",
    "Referrer-Policy",
]
_MARKET_BASE_PRICES: dict[str, float] = {
    "BTCUSDT": 45000.0,
    "ETHUSDT": 2500.0,
}
_MARKET_STATE: dict[str, dict[str, Any]] = {}
_LAST_PRICES: dict[str, float] = {}


def safe_resolve(base: Path, user_path: str) -> Path:
    """Resolve a user-provided path safely under a base directory."""

    root = base.resolve()
    candidate = (root / user_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SafetyError(f"path escapes base directory: {user_path}") from exc
    return candidate


def _workspace_path(user_path: str) -> Path:
    workspace = settings.workspace_dir.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return safe_resolve(workspace, user_path)


def _is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname in {"localhost", "127.0.0.1"}


def _validate_http_scheme(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ToolError(f"unsupported URL scheme: {parsed.scheme}")


def read_file(path: str) -> str:
    """Read a UTF-8 text file from the workspace."""

    resolved = _workspace_path(path)
    if not resolved.exists() or not resolved.is_file():
        raise ToolError(f"file does not exist: {path}")
    return resolved.read_text(encoding="utf-8")


def write_file(path: str, content: str) -> str:
    """Write a UTF-8 text file inside the workspace."""

    resolved = _workspace_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"written: {path}"


def list_files(path: str = ".") -> list[str]:
    """Return sorted relative file paths inside a workspace directory."""

    resolved = _workspace_path(path)
    if not resolved.exists():
        raise ToolError(f"path does not exist: {path}")
    if resolved.is_file():
        return [resolved.relative_to(settings.workspace_dir.resolve()).as_posix()]
    return sorted(
        entry.relative_to(settings.workspace_dir.resolve()).as_posix()
        for entry in resolved.rglob("*")
        if entry.is_file()
    )


def http_get(url: str, timeout: float | None = None) -> str:
    """Perform a safe HTTP GET request and return the response body."""

    _validate_http_scheme(url)
    request_timeout = timeout if timeout is not None else settings.http_timeout
    try:
        response = httpx.get(url, timeout=request_timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ToolError(str(exc)) from exc
    return response.text


def parse_csv(path: str) -> list[dict[str, str]]:
    """Parse a workspace CSV file into a list of dictionaries."""

    resolved = _workspace_path(path)
    if not resolved.exists() or not resolved.is_file():
        raise ToolError(f"file does not exist: {path}")
    with resolved.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def parse_html(html: str, selector: str = "a") -> list[str]:
    """Extract href or text values from matching HTML elements."""

    try:
        soup = BeautifulSoup(html, "html.parser")
        elements = soup.select(selector)
        results: list[str] = []
        for element in elements:
            href = element.get("href")
            text = href if href else element.get_text(strip=True)
            if text:
                results.append(text)
        return results
    except Exception as exc:
        raise ToolError(f"failed to parse html: {exc}") from exc


def http_request(
    url: str,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Perform a constrained HTTP request against safe targets."""

    _validate_http_scheme(url)
    allowed_methods = {"GET", "POST", "HEAD", "OPTIONS"}
    normalized_method = method.upper()
    if normalized_method not in allowed_methods:
        raise ToolError(f"disallowed HTTP method: {method}")
    if settings.safe_test_mode and not _is_safe_url(url):
        raise SafetyError("external URLs are blocked in safe_test_mode")

    try:
        with httpx.Client(timeout=settings.http_timeout, follow_redirects=True) as client:
            started = time.perf_counter()
            response = client.request(
                normalized_method,
                url,
                params=params,
                headers=headers,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            response.raise_for_status()
    except httpx.HTTPError as exc:
        if settings.safe_test_mode and _is_safe_url(url):
            logger.warning("local target %s unavailable, returning synthetic safe response: %s", url, exc)
            return {
                "status_code": 200,
                "headers": {"Server": "safe-simulated-localhost"},
                "body": "<html><body><a href='/health'>health</a><a href='/status'>status</a></body></html>",
                "url": url,
                "elapsed_ms": 0.0,
            }
        raise ToolError(str(exc)) from exc

    return {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "body": response.text,
        "url": str(response.url),
        "elapsed_ms": round(elapsed_ms, 3),
    }


def scan_headers(response: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a response for missing common security headers."""

    headers = {str(key): str(value) for key, value in dict(response.get("headers", {})).items()}
    present = [header for header in _SECURITY_HEADERS if header in headers]
    missing = [header for header in _SECURITY_HEADERS if header not in headers]
    if len(missing) >= 3:
        risk_level = "HIGH"
    elif missing:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"
    return {
        "missing": missing,
        "present": present,
        "risk_level": risk_level,
    }


def check_sql_injection(url: str) -> dict[str, Any]:
    """Run a simulation-only SQL injection check."""

    _validate_http_scheme(url)
    if not _is_safe_url(url):
        raise SafetyError("SQL injection simulation is limited to localhost targets")
    payloads = ["'", "1 OR 1=1", "'; DROP TABLE--"]
    return {
        "tested": True,
        "payloads_used": payloads,
        "vulnerable": False,
        "evidence": "safe-mode simulation completed without issues",
        "simulated": True,
    }


def check_xss(url: str) -> dict[str, Any]:
    """Run a simulation-only XSS check."""

    _validate_http_scheme(url)
    if not _is_safe_url(url):
        raise SafetyError("XSS simulation is limited to localhost targets")
    payloads = ["<script>alert(1)</script>", "<img src=x>"]
    return {
        "tested": True,
        "payloads_used": payloads,
        "vulnerable": False,
        "evidence": "safe-mode simulation completed without issues",
        "simulated": True,
    }


def port_scan(host: str, ports: list[int] | None = None) -> dict[str, Any]:
    """Scan a safe localhost target for open ports."""

    normalized_host = host.strip().lower()
    if settings.safe_test_mode and normalized_host not in {"localhost", "127.0.0.1"}:
        raise SafetyError("port scanning is limited to localhost in safe_test_mode")
    target_ports = ports if ports is not None else [80, 443, 8080, 8443, 3000, 5000]
    open_ports: list[int] = []
    closed_ports: list[int] = []
    started = time.perf_counter()
    for port in target_ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            result = sock.connect_ex((normalized_host, int(port)))
        if result == 0:
            open_ports.append(int(port))
        else:
            closed_ports.append(int(port))
    scan_time_ms = (time.perf_counter() - started) * 1000.0
    return {
        "host": normalized_host,
        "open_ports": open_ports,
        "closed_ports": closed_ports,
        "scan_time_ms": round(scan_time_ms, 3),
    }


def _market_rng(symbol: str) -> random.Random:
    seed = int(hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(seed)


def get_market_data(symbol: str) -> dict[str, Any]:
    """Return simulated or live market data for a trading symbol."""

    normalized_symbol = symbol.strip().upper()
    if normalized_symbol not in _MARKET_STATE:
        base_price = _MARKET_BASE_PRICES.get(normalized_symbol, 100.0)
        _MARKET_STATE[normalized_symbol] = {
            "price": base_price,
            "rng": _market_rng(normalized_symbol),
        }
        _LAST_PRICES[normalized_symbol] = base_price

    state = _MARKET_STATE[normalized_symbol]

    if settings.trading_mode == "live" and settings.binance_api_key and settings.binance_api_secret:
        try:
            response_text = http_get(
                f"https://api.binance.com/api/v3/ticker/price?symbol={normalized_symbol}",
                timeout=settings.http_timeout,
            )
            payload = json.loads(response_text)
            live_price = float(payload["price"])
            _LAST_PRICES[normalized_symbol] = live_price
            return {
                "symbol": normalized_symbol,
                "open": live_price,
                "high": live_price,
                "low": live_price,
                "close": live_price,
                "volume": 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "simulated": False,
            }
        except (ToolError, ValueError, KeyError, json.JSONDecodeError) as exc:
            logger.warning("live market fetch failed for %s, falling back to simulation: %s", normalized_symbol, exc)

    previous_close = float(state["price"])
    rng: random.Random = state["rng"]
    change_pct = rng.uniform(-0.01, 0.01)
    close_price = round(previous_close * (1.0 + change_pct), 6)
    high_price = round(max(previous_close, close_price) * (1.0 + rng.uniform(0.0, 0.003)), 6)
    low_price = round(min(previous_close, close_price) * (1.0 - rng.uniform(0.0, 0.003)), 6)
    volume = round(rng.uniform(10.0, 1000.0), 6)

    state["price"] = close_price
    _LAST_PRICES[normalized_symbol] = close_price

    return {
        "symbol": normalized_symbol,
        "open": previous_close,
        "high": max(high_price, previous_close, close_price),
        "low": min(low_price, previous_close, close_price),
        "close": close_price,
        "volume": volume,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "simulated": True,
    }


def calculate_indicators(
    prices: list[float],
    short_window: int,
    long_window: int,
) -> dict[str, Any]:
    """Calculate simple moving averages and a crossover signal."""

    prices_used = len(prices)
    short_ma = (
        sum(prices[-short_window:]) / short_window
        if prices_used >= short_window
        else None
    )
    long_ma = (
        sum(prices[-long_window:]) / long_window
        if prices_used >= long_window
        else None
    )

    signal = "HOLD"
    if short_ma is not None and long_ma is not None:
        if short_ma > long_ma:
            signal = "BUY"
        elif short_ma < long_ma:
            signal = "SELL"

    return {
        "short_ma": short_ma,
        "long_ma": long_ma,
        "signal": signal,
        "prices_used": prices_used,
    }


def place_order(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    mode: str = "paper",
) -> dict[str, Any]:
    """Place a paper order and return an immediate simulated fill."""

    normalized_side = side.strip().upper()
    if normalized_side not in {"BUY", "SELL"}:
        raise ToolError(f"invalid side: {side}")
    if qty <= 0:
        raise ToolError("qty must be > 0")
    if price <= 0:
        raise ToolError("price must be > 0")

    normalized_mode = mode.strip().lower()
    if normalized_mode != "paper":
        logger.warning("live execution is not configured; simulating order for mode=%s", mode)
        normalized_mode = "paper"

    normalized_symbol = symbol.strip().upper()
    _LAST_PRICES[normalized_symbol] = price
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "order_id": str(uuid4()),
        "symbol": normalized_symbol,
        "side": normalized_side,
        "qty": qty,
        "price": price,
        "filled": True,
        "fill_price": price,
        "timestamp": timestamp,
        "mode": normalized_mode,
    }


def get_portfolio(balance: float, positions: dict[str, float]) -> dict[str, Any]:
    """Return a portfolio valuation using last known prices."""

    total_value = float(balance)
    for symbol, qty in positions.items():
        total_value += float(qty) * float(_LAST_PRICES.get(symbol.upper(), 0.0))
    return {
        "balance": balance,
        "positions": positions,
        "total_value": total_value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "read_file": read_file,
    "write_file": write_file,
    "list_files": list_files,
    "http_get": http_get,
    "parse_csv": parse_csv,
    "parse_html": parse_html,
    "http_request": http_request,
    "scan_headers": scan_headers,
    "check_sql_injection": check_sql_injection,
    "check_xss": check_xss,
    "port_scan": port_scan,
    "get_market_data": get_market_data,
    "calculate_indicators": calculate_indicators,
    "place_order": place_order,
    "get_portfolio": get_portfolio,
}
