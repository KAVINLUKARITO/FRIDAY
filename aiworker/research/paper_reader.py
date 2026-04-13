"""Deterministic paper reader for local research artifacts."""

from __future__ import annotations

from typing import Any, Iterable

from aiworker.research.models import RawDocument


class PaperReader:
    """Extracts concise summaries and concepts from research documents."""

    def read(self, documents: Iterable[RawDocument]) -> dict[str, Any]:
        docs = list(documents)
        summaries = tuple(doc.content.strip().split(".")[0] for doc in docs if doc.content.strip())
        concepts = tuple(
            sorted(
                {
                    token.strip(" ,.;:()").lower()
                    for doc in docs
                    for token in doc.content.split()
                    if len(token.strip(" ,.;:()")) > 6
                }
            )[:10]
        )
        return {
            "documents_read": len(docs),
            "summaries": summaries,
            "concepts": concepts,
        }
