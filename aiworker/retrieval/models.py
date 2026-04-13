"""Data models for the safe retrieval layer — Phase 3."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RetrievalStatus(str, Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(frozen=True)
class RetrievalRequest:
    """Structured retrieval request with allowlist enforcement."""
    query: str
    allowed_domains: tuple[str, ...] = field(default_factory=tuple)
    max_results: int = 3
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class RetrievalResult:
    """Result from a sandboxed retrieval operation."""
    status: RetrievalStatus
    query: str
    content: str
    source_url: str
    blocked_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "query": self.query,
            "content": self.content,
            "source_url": self.source_url,
            "blocked_reason": self.blocked_reason,
        }
