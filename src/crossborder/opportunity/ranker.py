"""Composite opportunity ranking.

Fuses the signal kinds into one 0-100 opportunity score per niche. Weights
live here and nowhere else. When a signal is unavailable, its weight is
redistributed across the signals that did return data, so a missing source
degrades the score gracefully instead of zeroing it.
"""

from __future__ import annotations

from crossborder.opportunity.providers import DemandSignalProvider
from crossborder.opportunity.signals import (
    DemandSignal,
    NicheCandidate,
    OpportunityScore,
    SignalKind,
    SignalProvenance,
)

# How much each signal kind counts toward the final opportunity score.
DEFAULT_WEIGHTS: dict[SignalKind, float] = {
    SignalKind.trend_momentum: 0.20,   # external search trend from Google Trends
    SignalKind.demand_growth: 0.15,    # internal review velocity from timestamps
    SignalKind.surge: 0.15,            # short-term Best Sellers rank
    SignalKind.absolute_demand: 0.25,  # how big the niche is
    SignalKind.differentiation: 0.25,  # how beatable incumbents are
}


class OpportunityRanker:
    def __init__(
        self,
        providers: list[DemandSignalProvider],
        weights: dict[SignalKind, float] | None = None,
    ):
        self.providers = providers
        self.weights = weights or DEFAULT_WEIGHTS

    def score_one(self, candidate: NicheCandidate) -> OpportunityScore:
        signals: list[DemandSignal] = [p.fetch(candidate.keyword) for p in self.providers]

        usable = [
            s
            for s in signals
            if s.provenance != SignalProvenance.unavailable and s.kind in self.weights
        ]
        # Redistribute weight across only the signals that returned data.
        active_weight = sum(self.weights[s.kind] for s in usable)
        contribution: dict[str, float] = {}
        composite = 0.0
        if active_weight > 0:
            for s in usable:
                w = self.weights[s.kind] / active_weight
                part = s.score * w
                composite += part
                contribution[s.kind.value] = round(part, 1)

        present_kinds = {s.kind for s in usable}
        missing = [k.value for k in self.weights if k not in present_kinds]

        # Coverage discount: a candidate backed by only one signal (e.g. a pure
        # trend spike with no competitors in the catalog) should not outrank a
        # niche with real demand + differentiation evidence. Scale the composite
        # by how much of the total weight was actually backed by data.
        total_weight = sum(self.weights.values())
        coverage = active_weight / total_weight if total_weight else 0.0
        discounted = composite * (0.4 + 0.6 * coverage)

        return OpportunityScore(
            keyword=candidate.keyword,
            score=round(discounted, 1),
            signals=signals,
            discovery_source=candidate.source,
            contribution=contribution,
            missing_signals=missing,
            rationale=_rationale(usable, missing, coverage),
        )

    def rank(self, candidates: list[NicheCandidate]) -> list[OpportunityScore]:
        scored = [self.score_one(c) for c in candidates]
        scored.sort(key=lambda o: o.score, reverse=True)
        for i, item in enumerate(scored, start=1):
            item.rank = i
        return scored


def _rationale(usable: list[DemandSignal], missing: list[str], coverage: float) -> list[str]:
    lines = [f"{s.evidence}（{s.provider}·{s.provenance.value}）" for s in usable if s.evidence]
    if missing:
        lines.append(
            f"缺失信号：{', '.join(missing)}；信号覆盖度 {coverage * 100:.0f}%，"
            f"已按覆盖度对总分折扣（避免纯趋势词虚高）。"
        )
    return lines
