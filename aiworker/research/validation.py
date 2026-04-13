from aiworker.research.models import KnowledgeCluster, ResearchReport


def _compute_domain_diversity(report: ResearchReport) -> float:
    if report.total_sources == 0:
        return 0.0
    return min(len(report.unique_domains) / report.total_sources, 1.0)


def _compute_source_type_diversity(report: ResearchReport) -> float:
    return min(len(report.source_types) / 5, 1.0)


def _compute_claim_density(clusters: tuple[KnowledgeCluster, ...]) -> float:
    cluster_count: int = len(clusters)
    if cluster_count == 0:
        return 0.0
    total_claims: int = sum(
        len(c.consensus_points) + len(c.conflicting_points) for c in clusters
    )
    return min(total_claims / (cluster_count * 5), 1.0)


def _compute_contradiction_resolution(
    clusters: tuple[KnowledgeCluster, ...],
) -> float:
    if not clusters:
        return 0.0
    scores: list[float] = []
    for cluster in clusters:
        consensus: int = len(cluster.consensus_points)
        conflicting: int = len(cluster.conflicting_points)
        if conflicting == 0:
            scores.append(1.0)
        else:
            scores.append(consensus / (consensus + conflicting))
    return sum(scores) / len(scores)


def compute_coverage_score(report: ResearchReport) -> float:
    domain_div: float = _compute_domain_diversity(report)
    source_div: float = _compute_source_type_diversity(report)
    claim_den: float = _compute_claim_density(report.clusters)
    contra_res: float = _compute_contradiction_resolution(report.clusters)

    score: float = (
        domain_div * 0.3
        + source_div * 0.2
        + claim_den * 0.3
        + contra_res * 0.2
    )
    return round(max(0.0, min(1.0, score)), 4)


class ValidationEngine:

    def validate(self, report: ResearchReport) -> bool:
        if len(report.unique_domains) < 50:
            return False

        unique_source_types: set[str] = set(report.source_types)
        if len(unique_source_types) < 3:
            return False

        if report.coverage_score < 0.5:
            return False

        for cluster in report.clusters:
            if cluster.confidence_score < 0.3:
                return False

        return True
