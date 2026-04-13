from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchGoal:
    topic: str
    depth: int
    max_sources: int


@dataclass(frozen=True)
class SourceMetadata:
    url: str
    domain: str
    source_type: str
    authority_score: float


@dataclass(frozen=True)
class RawDocument:
    url: str
    domain: str
    content: str
    fetched_at: str


@dataclass(frozen=True)
class ExtractedKnowledge:
    summary: str
    key_concepts: tuple[str, ...]
    code_snippets: tuple[str, ...]
    claims: tuple[str, ...]
    risks: tuple[str, ...]
    source_domain: str


@dataclass(frozen=True)
class KnowledgeCluster:
    consensus_points: tuple[str, ...]
    conflicting_points: tuple[str, ...]
    implementation_steps: tuple[str, ...]
    confidence_score: float


@dataclass(frozen=True)
class ResearchReport:
    goal: ResearchGoal
    sources: tuple[SourceMetadata, ...]
    documents: tuple[RawDocument, ...]
    total_sources: int = 0
    unique_domains: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    clusters: tuple[KnowledgeCluster, ...] = ()
    coverage_score: float = 0.0
