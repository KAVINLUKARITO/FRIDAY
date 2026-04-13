import re
import string
from aiworker.research.models import ExtractedKnowledge, KnowledgeCluster

_NEGATION_TOKENS: frozenset[str] = frozenset(
    ("not", "never", "no", "cannot", "fails", "false")
)

_PUNCTUATION_TABLE: dict[int, None] = str.maketrans("", "", string.punctuation)


def _normalize_text(text: str) -> str:
    result: str = text.lower().strip()
    return re.sub(r"\s+", " ", result)


def _tokenize(text: str) -> list[str]:
    lowered: str = text.lower()
    stripped: str = lowered.translate(_PUNCTUATION_TABLE)
    return stripped.split()


def _word_set(text: str) -> set[str]:
    return set(_tokenize(text))


def _has_negation(words: set[str]) -> bool:
    return bool(words & _NEGATION_TOKENS)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _find_root(parent: dict[int, int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _union(parent: dict[int, int], rank: dict[int, int], a: int, b: int) -> None:
    ra: int = _find_root(parent, a)
    rb: int = _find_root(parent, b)
    if ra == rb:
        return
    if rank[ra] < rank[rb]:
        ra, rb = rb, ra
    parent[rb] = ra
    if rank[ra] == rank[rb]:
        rank[ra] += 1


class ClusteringEngine:

    def synthesize(
        self, extracted: list[ExtractedKnowledge]
    ) -> list[KnowledgeCluster]:
        if not extracted:
            raise ValueError("extracted must not be empty")

        for i, ek in enumerate(extracted):
            if not ek.key_concepts:
                raise ValueError(
                    f"ExtractedKnowledge at index {i} has empty key_concepts"
                )

        # 1 - Build concept → document indices mapping
        concept_to_indices: dict[str, list[int]] = {}
        for idx, ek in enumerate(extracted):
            for concept in ek.key_concepts:
                norm: str = _normalize_text(concept)
                if norm not in concept_to_indices:
                    concept_to_indices[norm] = []
                concept_to_indices[norm].append(idx)

        # 2 - Connected components via union-find
        parent: dict[int, int] = {i: i for i in range(len(extracted))}
        rank: dict[int, int] = {i: 0 for i in range(len(extracted))}

        for indices in concept_to_indices.values():
            for j in range(1, len(indices)):
                _union(parent, rank, indices[0], indices[j])

        # 3 - Group documents by component root
        components: dict[int, list[int]] = {}
        for i in range(len(extracted)):
            root: int = _find_root(parent, i)
            if root not in components:
                components[root] = []
            components[root].append(i)

        # 4 - Build each cluster
        clusters: list[KnowledgeCluster] = []
        for doc_indices in components.values():
            cluster: KnowledgeCluster = _build_cluster(
                [extracted[i] for i in doc_indices]
            )
            clusters.append(cluster)

        # 5 - Sort: confidence descending, then first consensus_point ascending
        clusters.sort(
            key=lambda c: (
                -c.confidence_score,
                c.consensus_points[0] if c.consensus_points else "",
            )
        )

        return clusters


def _build_cluster(docs: list[ExtractedKnowledge]) -> KnowledgeCluster:
    # --- Claim merging ---
    seen_normalized: dict[str, str] = {}
    for doc in docs:
        for claim in doc.claims:
            norm: str = _normalize_text(claim)
            if norm not in seen_normalized:
                seen_normalized[norm] = claim

    unique_claims: list[str] = list(seen_normalized.values())
    total_claims: int = len(unique_claims)

    # --- Conflict detection ---
    conflicting_indices: set[int] = set()
    for i in range(len(unique_claims)):
        for j in range(i + 1, len(unique_claims)):
            words_i: set[str] = _word_set(unique_claims[i])
            words_j: set[str] = _word_set(unique_claims[j])
            if _jaccard(words_i, words_j) < 0.5:
                continue
            neg_i: bool = _has_negation(words_i)
            neg_j: bool = _has_negation(words_j)
            if neg_i != neg_j:
                conflicting_indices.add(i)
                conflicting_indices.add(j)

    consensus: list[str] = [
        c for i, c in enumerate(unique_claims) if i not in conflicting_indices
    ]
    conflicting: list[str] = [
        c for i, c in enumerate(unique_claims) if i in conflicting_indices
    ]

    # --- Implementation steps from code_snippets ---
    steps_seen: dict[str, str] = {}
    for doc in docs:
        for snippet in doc.code_snippets:
            if not snippet.strip():
                continue
            norm_snip: str = _normalize_text(snippet)
            if norm_snip not in steps_seen:
                steps_seen[norm_snip] = snippet
    impl_steps: list[str] = list(steps_seen.values())

    # --- Confidence ---
    unique_domains: set[str] = {doc.source_domain for doc in docs}
    domain_diversity: float = len(unique_domains) / len(docs) if docs else 0.0

    if total_claims == 0:
        confidence: float = 0.0
    else:
        consensus_ratio: float = len(consensus) / total_claims
        confidence = consensus_ratio * 0.6 + domain_diversity * 0.4

    confidence = round(max(0.0, min(1.0, confidence)), 4)

    # --- Sort all outputs lexicographically ---
    consensus.sort()
    conflicting.sort()
    impl_steps.sort()

    return KnowledgeCluster(
        consensus_points=tuple(consensus),
        conflicting_points=tuple(conflicting),
        implementation_steps=tuple(impl_steps),
        confidence_score=confidence,
    )
