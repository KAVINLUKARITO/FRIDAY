"""Built-in task-agent tools."""

from __future__ import annotations

import logging
import platform
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel, Field, field_validator

from aiworker.config import AIWorkerConfig
from aiworker.models import ToolDefinition, ToolResult
from aiworker.tools.tool_registry import ToolRegistry, tool_registry

logger = logging.getLogger(__name__)


class EchoInput(BaseModel):
    text: str = Field(min_length=1)


class ListFilesInput(BaseModel):
    path: str = "."
    pattern: str = "*"
    max_results: int = Field(default=50, ge=1, le=500)


class ReadFileInput(BaseModel):
    path: str = Field(min_length=1)
    max_bytes: int = Field(default=20000, ge=1, le=200000)


class HttpGetInput(BaseModel):
    url: str = Field(min_length=1)
    timeout_seconds: float = Field(default=10.0, gt=0.0, le=60.0)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return value


class SystemInfoInput(BaseModel):
    include_environment: bool = False


def _safe_resolve(base_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = base_path / candidate
    resolved = candidate.resolve()
    base = base_path.resolve()
    if base not in (resolved, *resolved.parents):
        raise ValueError(f"path is outside AIWORKER_BASE_PATH: {raw_path}")
    return resolved


def echo_tool(model: BaseModel) -> ToolResult:
    payload = EchoInput.model_validate(model)
    return ToolResult(success=True, tool_name="echo", data={"text": payload.text})


def make_list_files_tool(config: AIWorkerConfig):
    def list_files_tool(model: BaseModel) -> ToolResult:
        payload = ListFilesInput.model_validate(model)
        try:
            path = _safe_resolve(config.base_path, payload.path)
            if not path.exists():
                return ToolResult(success=False, tool_name="list_files", error=f"path does not exist: {path}")
            files = []
            for child in path.glob(payload.pattern):
                files.append(
                    {
                        "path": str(child.relative_to(config.base_path)),
                        "is_dir": child.is_dir(),
                        "size": child.stat().st_size if child.is_file() else None,
                    }
                )
                if len(files) >= payload.max_results:
                    break
            return ToolResult(success=True, tool_name="list_files", data={"files": files})
        except Exception as exc:
            logger.exception("list_files failed")
            return ToolResult(success=False, tool_name="list_files", error=str(exc))

    return list_files_tool


def make_read_file_tool(config: AIWorkerConfig):
    def read_file_tool(model: BaseModel) -> ToolResult:
        payload = ReadFileInput.model_validate(model)
        try:
            path = _safe_resolve(config.base_path, payload.path)
            if not path.is_file():
                return ToolResult(success=False, tool_name="read_file", error=f"not a file: {path}")
            content = path.read_text(encoding="utf-8", errors="replace")[: payload.max_bytes]
            return ToolResult(
                success=True,
                tool_name="read_file",
                data={"path": str(path.relative_to(config.base_path)), "content": content},
            )
        except Exception as exc:
            logger.exception("read_file failed")
            return ToolResult(success=False, tool_name="read_file", error=str(exc))

    return read_file_tool


def http_get_tool(model: BaseModel) -> ToolResult:
    payload = HttpGetInput.model_validate(model)
    try:
        response = requests.get(payload.url, timeout=payload.timeout_seconds)
        return ToolResult(
            success=response.ok,
            tool_name="http_get",
            data={
                "status_code": response.status_code,
                "text": response.text[:5000],
                "headers": dict(response.headers),
            },
            error=None if response.ok else response.reason,
        )
    except requests.RequestException as exc:
        logger.exception("http_get failed")
        return ToolResult(success=False, tool_name="http_get", error=str(exc))


def system_info_tool(model: BaseModel) -> ToolResult:
    payload = SystemInfoInput.model_validate(model)
    data: dict[str, Any] = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
    }
    if payload.include_environment:
        data["environment"] = {"AIWORKER_ENV": platform.node()}
    return ToolResult(success=True, tool_name="system_info", data=data)


def register_builtin_tools(
    config: AIWorkerConfig,
    registry: ToolRegistry = tool_registry,
) -> ToolRegistry:
    registry.register(
        ToolDefinition(name="echo", description="Return input text unchanged.", capabilities=("format",)),
        EchoInput,
        echo_tool,
    )
    registry.register(
        ToolDefinition(name="list_files", description="List files under the configured project root.", capabilities=("file", "inspect")),
        ListFilesInput,
        make_list_files_tool(config),
    )
    registry.register(
        ToolDefinition(name="read_file", description="Read a text file under the configured project root.", capabilities=("file", "inspect")),
        ReadFileInput,
        make_read_file_tool(config),
    )
    registry.register(
        ToolDefinition(name="http_get", description="Fetch a URL with timeout and structured errors.", capabilities=("network",)),
        HttpGetInput,
        http_get_tool,
    )
    registry.register(
        ToolDefinition(name="system_info", description="Return local Python and platform metadata.", capabilities=("inspect",)),
        SystemInfoInput,
        system_info_tool,
    )
    return registry
