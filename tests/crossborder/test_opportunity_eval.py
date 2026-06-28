from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crossborder.opportunity.eval import (  # noqa: E402
    eval_noise_filter,
    eval_signal_ablation,
    eval_signal_coverage,
    run_opportunity_eval,
)
from crossborder.opportunity.ranker import OpportunityRanker  # noqa: E402
from crossborder.opportunity.signals import (  # noqa: E402
    DemandSignal,
    NicheCandidate,
    OpportunityScore,
    SignalKind,
    SignalProvenance,
)


class StubIndex:
    def __init__(self, valid: set[str]):
        self.valid = valid

    def match(self, keyword, min_reviews=50, top_n=20):
        return [{"asin": "A", "review_count": 100, "rating": 4.2}] if keyword in self.valid else []


class FixedProvider:
    def __init__(self, kind: SignalKind, scores: dict[str, float], name: str | None = None):
        self.kind = kind
        self.name = name or kind.value
        self.scores = scores

    def fetch(self, keyword: str) -> DemandSignal:
        score = self.scores.get(keyword)
        if score is None:
            return DemandSignal(
                kind=self.kind,
                provider=self.name,
                score=0,
                provenance=SignalProvenance.unavailable,
            )
        return DemandSignal(
            kind=self.kind,
            provider=self.name,
            score=score,
            provenance=SignalProvenance.proxy,
            evidence=f"{keyword}={score}",
        )


class OpportunityEvalTest(unittest.TestCase):
    def test_eval_noise_filter_counts_confusion_and_f1(self):
        labels = [
            {"query": "good niche", "is_niche": True},
            {"query": "another niche", "is_niche": True},
            {"query": "brand noise", "is_niche": False},
            {"query": "bad miss", "is_niche": False},
        ]
        index = StubIndex({"good niche", "brand noise"})

        out = eval_noise_filter(labels, index)

        self.assertEqual(out["confusion"], {"tp": 1, "fp": 1, "tn": 1, "fn": 1})
        self.assertAlmostEqual(out["precision"], 0.5)
        self.assertAlmostEqual(out["recall"], 0.5)
        self.assertAlmostEqual(out["f1"], 0.5)
        self.assertEqual(len(out["misclassified"]), 2)

    def test_eval_signal_coverage_counts_histogram_and_provenance(self):
        opportunities = [
            OpportunityScore(
                keyword="a",
                score=80,
                signals=[
                    DemandSignal(kind=SignalKind.trend_momentum, provider="p1", provenance=SignalProvenance.live),
                    DemandSignal(kind=SignalKind.surge, provider="p2", provenance=SignalProvenance.snapshot),
                    DemandSignal(kind=SignalKind.absolute_demand, provider="p3", provenance=SignalProvenance.proxy),
                    DemandSignal(kind=SignalKind.differentiation, provider="p4", provenance=SignalProvenance.unavailable),
                ],
            ),
            OpportunityScore(
                keyword="b",
                score=60,
                signals=[
                    DemandSignal(kind=SignalKind.trend_momentum, provider="p1", provenance=SignalProvenance.unavailable),
                    DemandSignal(kind=SignalKind.surge, provider="p2", provenance=SignalProvenance.unavailable),
                ],
            ),
        ]

        out = eval_signal_coverage(opportunities)

        self.assertEqual(out["coverage_histogram"]["3"], 1)
        self.assertEqual(out["coverage_histogram"]["0"], 1)
        self.assertEqual(out["provenance_breakdown"]["live"], 1)
        self.assertEqual(out["provenance_breakdown"]["unavailable"], 3)
        self.assertEqual(out["avg_usable_signals"], 1.5)

    def test_eval_signal_ablation_detects_top1_change(self):
        providers = [
            FixedProvider(SignalKind.trend_momentum, {"a": 100, "b": 10, "c": 10}, "trend"),
            FixedProvider(SignalKind.absolute_demand, {"a": 10, "b": 100, "c": 40}, "demand"),
            FixedProvider(SignalKind.differentiation, {"a": 10, "b": 60, "c": 80}, "diff"),
        ]
        candidates = [
            NicheCandidate(keyword="a"),
            NicheCandidate(keyword="b"),
            NicheCandidate(keyword="c"),
        ]
        baseline = OpportunityRanker(providers).rank(candidates)

        out = eval_signal_ablation(baseline, "a", providers=providers)

        self.assertEqual(len(out["ablations"]), 3)
        self.assertTrue(any(item["top1_changed"] for item in out["ablations"]))
        self.assertTrue(all(item["displacement"] >= 0 for item in out["ablations"]))

    def test_dataset_gated_run_opportunity_eval(self):
        meta = ROOT / "data" / "amazon_reviews_2023" / "meta_Health_and_Personal_Care.jsonl"
        if not meta.exists():
            self.skipTest("Amazon dataset not downloaded")

        out = run_opportunity_eval(seed="neck massager")

        self.assertIn("noise_filter", out)
        self.assertIn("signal_coverage", out)
        self.assertIn("ablation", out)
        self.assertIn("degradation", out)
        self.assertGreaterEqual(out["noise_filter"]["f1"], 0)
        self.assertLessEqual(out["noise_filter"]["f1"], 1)


if __name__ == "__main__":
    unittest.main()
