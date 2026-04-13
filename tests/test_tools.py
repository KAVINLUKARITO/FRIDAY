from __future__ import annotations

import csv
from pathlib import Path

import httpx
import pytest

import tools
from tools import SafetyError, ToolError, http_get, list_files, parse_csv, read_file, write_file


@pytest.fixture(autouse=True)
def configure_tools_workspace(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools.settings, "workspace_dir", workspace)
    monkeypatch.setattr(tools.settings, "http_timeout", 1.0)


def test_read_file_returns_content_of_existing_file(workspace: Path) -> None:
    target = workspace / "sample.txt"
    target.write_text("hello", encoding="utf-8")

    assert read_file("sample.txt") == "hello"


def test_read_file_raises_tool_error_for_missing_file(workspace: Path) -> None:
    with pytest.raises(ToolError):
        read_file("missing.txt")


def test_read_file_raises_safety_error_for_path_outside_workspace(workspace: Path) -> None:
    with pytest.raises(SafetyError):
        read_file("../outside.txt")


def test_write_file_creates_file_with_correct_content(workspace: Path) -> None:
    result = write_file("nested/out.txt", "content")

    assert result == "written: nested/out.txt"
    assert (workspace / "nested" / "out.txt").read_text(encoding="utf-8") == "content"


def test_write_file_raises_safety_error_for_path_outside_workspace(workspace: Path) -> None:
    with pytest.raises(SafetyError):
        write_file("../outside.txt", "bad")


def test_list_files_returns_sorted_file_list(workspace: Path) -> None:
    (workspace / "b.txt").write_text("b", encoding="utf-8")
    nested = workspace / "nested"
    nested.mkdir()
    (nested / "a.txt").write_text("a", encoding="utf-8")

    assert list_files(".") == ["b.txt", "nested/a.txt"]


def test_list_files_raises_safety_error_for_path_outside_workspace(workspace: Path) -> None:
    with pytest.raises(SafetyError):
        list_files("../outside")


def test_http_get_returns_body_for_200_response(
    monkeypatch: pytest.MonkeyPatch,
    workspace: Path,
) -> None:
    class Response:
        text = "ok"

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, timeout: float) -> Response:
        assert url == "https://example.com"
        assert timeout == 1.0
        return Response()

    monkeypatch.setattr(tools.httpx, "get", fake_get)

    assert http_get("https://example.com") == "ok"


def test_http_get_raises_tool_error_for_404_response(
    monkeypatch: pytest.MonkeyPatch,
    workspace: Path,
) -> None:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status_code=404, request=request)

    class Response:
        text = "missing"

        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr(tools.httpx, "get", lambda url, timeout: Response())

    with pytest.raises(ToolError):
        http_get("https://example.com")


def test_http_get_raises_tool_error_for_non_http_scheme(workspace: Path) -> None:
    with pytest.raises(ToolError):
        http_get("ftp://example.com")


def test_parse_csv_returns_correct_list_of_dicts(workspace: Path) -> None:
    target = workspace / "sample.csv"
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "value"])
        writer.writeheader()
        writer.writerow({"name": "alpha", "value": "1"})
        writer.writerow({"name": "beta", "value": "2"})

    rows = parse_csv("sample.csv")

    assert rows == [{"name": "alpha", "value": "1"}, {"name": "beta", "value": "2"}]


def test_parse_csv_raises_safety_error_for_path_outside_workspace(workspace: Path) -> None:
    with pytest.raises(SafetyError):
        parse_csv("../outside.csv")
