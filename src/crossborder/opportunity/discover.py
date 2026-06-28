"""End-to-end opportunity discovery: seed keyword -> ranked niche opportunities.

Flow:
1. Build the candidate set: the seed itself plus Google Trends rising queries
   (this is where keywords come from when no human supplies them).
2. Score every candidate with all configured providers.
3. Return the ranked opportunity list.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossborder.opportunity.dataset_index import DatasetIndex
from crossborder.opportunity.providers import (
    AmazonSnapshotProvider,
    DifferentiationProvider,
    GoogleTrendsProvider,
    ReviewDemandProvider,
    ReviewVelocityProvider,
)
from crossborder.opportunity.ranker import OpportunityRanker
from crossborder.opportunity.signals import NicheCandidate, OpportunityScore

# Captured Amazon "Massagers" sub-category Best Sellers snapshot. Amazon serves
# a degraded page to non-browser clients, so this is a one-time captured fixture
# (provenance=snapshot); production fronts the same provider with a scraping API.
DEFAULT_SNAPSHOT = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "crossborder"
    / "amazon_bestsellers_snapshot.json"
)


def build_default_engine(
    snapshot_path: Path | None = None,
) -> tuple[OpportunityRanker, GoogleTrendsProvider]:
    index = DatasetIndex()
    trends = GoogleTrendsProvider()
    if snapshot_path is None and DEFAULT_SNAPSHOT.exists():
        snapshot_path = DEFAULT_SNAPSHOT
    ranker = OpportunityRanker(
        providers=[
            trends,
            ReviewVelocityProvider(index),
            ReviewDemandProvider(index),
            DifferentiationProvider(index),
            AmazonSnapshotProvider(snapshot_path),
        ]
    )
    return ranker, trends


# Tokens that mark a rising query as brand/intent noise rather than a niche.
_NOISE_TOKENS = {"reviews", "review", "amazon", "vs", "coupon", "manual", "app"}


def _is_sellable_niche(keyword: str, index) -> bool:
    """Keep only rising queries that map to a real, catalog-backed niche.

    A query is dropped if it carries intent/brand noise tokens or if no listing
    with enough reviews matches it — if nobody is selling it on Amazon yet, it
    is a trend to watch, not an actionable niche to enter.
    """
    tokens = set(keyword.lower().split())
    if tokens & _NOISE_TOKENS:
        return False
    return bool(index.match(keyword, min_reviews=50, top_n=1))


def discover(
    seed_keyword: str,
    max_candidates: int = 8,
    snapshot_path: Path | None = None,
) -> list[OpportunityScore]:
    ranker, trends = build_default_engine(snapshot_path)
    index = next(p.index for p in ranker.providers if hasattr(p, "index"))
    candidates = [NicheCandidate(keyword=seed_keyword, source="manual", note="种子词")]
    for cand in trends.discover_rising(seed_keyword):
        if cand.keyword in {c.keyword for c in candidates}:
            continue
        if not _is_sellable_niche(cand.keyword, index):
            continue
        candidates.append(cand)
        if len(candidates) >= max_candidates:
            break
    return ranker.rank(candidates)


def main() -> None:
    seed = sys.argv[1] if len(sys.argv) > 1 else "neck massager"
    results = discover(seed)
    print(f"\n种子词 '{seed}' → 发现并排序 {len(results)} 个机会赛道:\n")
    for o in results:
        print(f"#{o.rank}  {o.keyword:42}  机会分 {o.score:5.1f}  （来源:{o.discovery_source}）")
        for line in o.rationale:
            print(f"      - {line}")
        print()


if __name__ == "__main__":
    main()
