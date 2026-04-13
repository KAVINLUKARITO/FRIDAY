from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import tools
from tools import (
    SafetyError,
    ToolError,
    calculate_indicators,
    check_sql_injection,
    check_xss,
    get_market_data,
    http_get,
    http_request,
    list_files,
    place_order,
    port_scan,
    read_file,
    scan_headers,
    write_file,
)


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    monkeypatch.setattr(tools.settings, "workspace_dir", workspace_dir)
    monkeypatch.setattr(tools.settings, "safe_test_mode", True)
    monkeypatch.setattr(tools.settings, "trading_mode", "paper")
    return workspace_dir


def test_read_file_returns_content(workspace: Path) -> None:
    (workspace / "sample.txt").write_text("hello", encoding="utf-8")
    assert read_file("sample.txt") == "hello"


def test_read_file_raises_tool_error_for_missing_file(workspace: Path) -> None:
    with pytest.raises(ToolError):
        read_file("missing.txt")


def test_read_file_raises_safety_error_for_path_escape(workspace: Path) -> None:
    with pytest.raises(SafetyError):
        read_file("../escape.txt")


def test_write_file_creates_file(workspace: Path) -> None:
    result = write_file("nested/output.txt", "data")
    assert result == "written: nested/output.txt"
    assert (workspace / "nested" / "output.txt").read_text(encoding="utf-8") == "data"


def test_write_file_raises_safety_error_for_path_escape(workspace: Path) -> None:
    with pytest.raises(SafetyError):
        write_file("../escape.txt", "bad")


def test_list_files_returns_sorted_list(workspace: Path) -> None:
    (workspace / "b.txt").write_text("b", encoding="utf-8")
    nested = workspace / "nested"
    nested.mkdir()
    (nested / "a.txt").write_text("a", encoding="utf-8")
    assert list_files(".") == ["b.txt", "nested/a.txt"]


def test_http_get_returns_body_for_200(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    class Response:
        text = "ok"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(tools.httpx, "get", lambda url, timeout: Response())
    assert http_get("https://example.com") == "ok"


def test_http_get_raises_tool_error_for_404(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status_code=404, request=request)

    class Response:
        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr(tools.httpx, "get", lambda url, timeout: Response())
    with pytest.raises(ToolError):
        http_get("https://example.com")


def test_http_request_blocks_external_urls_in_safe_test_mode(workspace: Path) -> None:
    with pytest.raises(SafetyError):
        http_request("http://example.com")


def test_scan_headers_returns_low_for_all_headers_present(workspace: Path) -> None:
    response = {"headers": {header: "set" for header in tools._SECURITY_HEADERS}}
    result = scan_headers(response)
    assert result["risk_level"] == "LOW"


def test_scan_headers_returns_high_for_three_missing(workspace: Path) -> None:
    response = {"headers": {"X-Frame-Options": "DENY"}}
    result = scan_headers(response)
    assert result["risk_level"] == "HIGH"


def test_check_sql_injection_returns_simulated_result(workspace: Path) -> None:
    result = check_sql_injection("http://localhost:8080")
    assert result["tested"] is True
    assert result["simulated"] is True


def test_check_xss_returns_simulated_result(workspace: Path) -> None:
    result = check_xss("http://localhost:8080")
    assert result["tested"] is True
    assert result["simulated"] is True


def test_port_scan_returns_open_ports_list_for_localhost(
    monkeypatch: pytest.MonkeyPatch,
    workspace: Path,
) -> None:
    class FakeSocket:
        def __enter__(self) -> "FakeSocket":
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def settimeout(self, timeout: float) -> None:
            return None

        def connect_ex(self, address: tuple[str, int]) -> int:
            return 0 if address[1] == 8080 else 1

    monkeypatch.setattr(tools.socket, "socket", lambda *args, **kwargs: FakeSocket())
    result = port_scan("localhost", [8080, 8081])
    assert result["open_ports"] == [8080]


def test_get_market_data_returns_ohlcv_dict(workspace: Path) -> None:
    result = get_market_data("BTCUSDT")
    assert set(result) >= {"symbol", "open", "high", "low", "close", "volume", "timestamp", "simulated"}


def test_calculate_indicators_returns_signal(workspace: Path) -> None:
    result = calculate_indicators([1, 2, 3, 4, 5, 6], short_window=2, long_window=4)
    assert result["signal"] == "BUY"


def test_calculate_indicators_returns_hold_when_insufficient_data(workspace: Path) -> None:
    result = calculate_indicators([1, 2], short_window=5, long_window=10)
    assert result["signal"] == "HOLD"


def test_place_order_returns_filled_order_for_paper_mode(workspace: Path) -> None:
    result = place_order("BTCUSDT", "BUY", 0.1, 100.0, mode="paper")
    assert result["filled"] is True
    assert result["mode"] == "paper"


def test_place_order_raises_tool_error_for_invalid_side(workspace: Path) -> None:
    with pytest.raises(ToolError):
        place_order("BTCUSDT", "HOLD", 0.1, 100.0)


def test_place_order_raises_tool_error_for_non_positive_qty(workspace: Path) -> None:
    with pytest.raises(ToolError):
        place_order("BTCUSDT", "BUY", 0.0, 100.0)
