"""Unit tests for the opportunity discovery engine.

These avoid the network (no real Google Trends call) and the 300MB dataset by
using a small in-memory stub index. One dataset-gated integration test runs the
real deep-dive when the data files are present.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crossborder.opportunity.providers import (  # noqa: E402
    AmazonSnapshotProvider,
    DifferentiationProvider,
    GoogleTrendsProvider,
    ReviewDemandProvider,
    ReviewVelocityProvider,
)
from crossborder.opportunity.ranker import OpportunityRanker  # noqa: E402
from crossborder.opportunity.signals import (  # noqa: E402
    NicheCandidate,
    SignalKind,
    SignalProvenance,
)


class StubIndex:
    """Minimal duck-typed DatasetIndex for provider tests."""

    def __init__(self, pool, digest):
        self._pool = pool
        self.digest = digest

    def match(self, keyword, min_reviews=50, top_n=20):
        # Return the configured pool only for keywords we "know".
        if keyword in {"neck massager", "good niche", "electric neck massager"}:
            return [r for r in self._pool if r["review_count"] >= min_reviews][:top_n]
        return []


def _pool():
    return [
        {"asin": "A1", "title": "Neck Massager A", "review_count": 2000, "rating": 4.4, "price": 40},
        {"asin": "A2", "title": "Neck Massager B", "review_count": 800, "rating": 4.1, "price": None},
        {"asin": "A3", "title": "Neck Massager C", "review_count": 300, "rating": 3.9, "price": None},
    ]


def _digest():
    return {
        "A1": {
            "total": 2000,
            "negative": 400,
            "pains": {"做工差/易坏": 120, "电池/续航": 30},
            "recent_reviews": 120,
            "prior_reviews": 60,
        },
        "A2": {
            "total": 800,
            "negative": 80,
            "pains": {"做工差/易坏": 20},
            "recent_reviews": 80,
            "prior_reviews": 40,
        },
        "A3": {
            "total": 300,
            "negative": 90,
            "pains": {"尺寸/贴合差": 25},
            "recent_reviews": 0,
            "prior_reviews": 0,
        },
    }


class ReviewDemandProviderTest(unittest.TestCase):
    def test_demand_scales_with_total_reviews(self):
        prov = ReviewDemandProvider(StubIndex(_pool(), _digest()))
        sig = prov.fetch("neck massager")
        self.assertEqual(sig.kind, SignalKind.absolute_demand)
        self.assertEqual(sig.provenance, SignalProvenance.proxy)
        self.assertGreater(sig.score, 50)  # 3100 reviews -> healthy demand
        self.assertEqual(sig.detail["total_reviews"], 3100)

    def test_unknown_keyword_is_unavailable(self):
        prov = ReviewDemandProvider(StubIndex(_pool(), _digest()))
        sig = prov.fetch("nonexistent niche")
        self.assertEqual(sig.provenance, SignalProvenance.unavailable)
        self.assertEqual(sig.score, 0.0)


class DifferentiationProviderTest(unittest.TestCase):
    def test_high_negative_density_means_more_room(self):
        prov = DifferentiationProvider(StubIndex(_pool(), _digest()))
        sig = prov.fetch("neck massager")
        self.assertEqual(sig.kind, SignalKind.differentiation)
        # 570 negative / 3100 total = ~18% -> score 25 + 0.184*200 ~= 62
        self.assertGreater(sig.score, 50)
        self.assertEqual(sig.detail["top_pains"][0][0], "做工差/易坏")

    def test_no_digest_coverage_falls_back(self):
        prov = DifferentiationProvider(StubIndex(_pool(), {}))
        sig = prov.fetch("neck massager")
        self.assertEqual(sig.provenance, SignalProvenance.proxy)
        self.assertEqual(sig.score, 40.0)


class ReviewVelocityProviderTest(unittest.TestCase):
    def test_review_growth_maps_to_high_score(self):
        prov = ReviewVelocityProvider(StubIndex(_pool(), _digest()))
        sig = prov.fetch("neck massager")
        self.assertEqual(sig.kind, SignalKind.demand_growth)
        self.assertEqual(sig.provenance, SignalProvenance.proxy)
        self.assertAlmostEqual(sig.detail["growth"], 2.0)
        self.assertAlmostEqual(sig.score, 80.0, delta=0.1)

    def test_flat_review_growth_maps_to_neutral_score(self):
        digest = {
            "A1": {"recent_reviews": 50, "prior_reviews": 50},
            "A2": {"recent_reviews": 30, "prior_reviews": 30},
            "A3": {"recent_reviews": 20, "prior_reviews": 20},
        }
        prov = ReviewVelocityProvider(StubIndex(_pool(), digest))
        sig = prov.fetch("neck massager")
        self.assertAlmostEqual(sig.detail["growth"], 1.0)
        self.assertAlmostEqual(sig.score, 40.0, delta=0.1)

    def test_missing_review_windows_falls_back_to_low_confidence_proxy(self):
        digest = {
            "A1": {"total": 2000, "negative": 400, "pains": {}},
            "A2": {"total": 800, "negative": 80, "pains": {}},
            "A3": {"total": 300, "negative": 90, "pains": {}},
        }
        prov = ReviewVelocityProvider(StubIndex(_pool(), digest))
        sig = prov.fetch("neck massager")
        self.assertEqual(sig.provenance, SignalProvenance.proxy)
        self.assertEqual(sig.score, 40.0)
        self.assertLess(sig.confidence, 0.5)


class AmazonSnapshotProviderTest(unittest.TestCase):
    def setUp(self):
        self.snap = ROOT / "tests" / "crossborder" / "fixtures" / "_tmp_snapshot.json"
        self.snap.write_text(
            json.dumps(
                [
                    {"rank": 3, "title": "Electric Neck Massager Pro", "is_mover": True},
                    {"rank": 40, "title": "Foot Massager", "is_mover": False},
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.snap.unlink(missing_ok=True)

    def test_rank_maps_to_score(self):
        prov = AmazonSnapshotProvider(self.snap)
        sig = prov.fetch("electric neck massager")
        self.assertEqual(sig.provenance, SignalProvenance.snapshot)
        self.assertEqual(sig.detail["rank"], 3)
        self.assertGreater(sig.score, 90)  # rank 3 -> high

    def test_missing_snapshot_is_unavailable(self):
        prov = AmazonSnapshotProvider(ROOT / "does_not_exist.json")
        sig = prov.fetch("neck massager")
        self.assertEqual(sig.provenance, SignalProvenance.unavailable)


class SlopeTest(unittest.TestCase):
    def test_rising_series_positive_slope(self):
        series = [10] * 18 + [30] * 18 + [60] * 18
        slope = GoogleTrendsProvider._slope_pct(series)
        self.assertGreater(slope, 400)  # 10 -> 60

    def test_too_short_series_returns_none(self):
        self.assertIsNone(GoogleTrendsProvider._slope_pct([1, 2, 3]))


class RankerTest(unittest.TestCase):
    """Ranker logic with handcrafted providers — no network, no dataset."""

    class FixedProvider:
        def __init__(self, kind, name, score, provenance=SignalProvenance.proxy):
            self.kind = kind
            self.name = name
            self._score = score
            self._prov = provenance

        def fetch(self, keyword):
            from crossborder.opportunity.signals import DemandSignal

            return DemandSignal(
                kind=self.kind,
                provider=self.name,
                score=self._score,
                provenance=self._prov,
                evidence="x",
            )

    def test_full_coverage_not_discounted(self):
        providers = [
            self.FixedProvider(SignalKind.trend_momentum, "t", 80),
            self.FixedProvider(SignalKind.demand_growth, "v", 80),
            self.FixedProvider(SignalKind.surge, "s", 80),
            self.FixedProvider(SignalKind.absolute_demand, "d", 80),
            self.FixedProvider(SignalKind.differentiation, "f", 80),
        ]
        ranker = OpportunityRanker(providers)
        out = ranker.score_one(NicheCandidate(keyword="x"))
        # All signals 80, full coverage -> composite 80, no discount.
        self.assertAlmostEqual(out.score, 80.0, delta=0.1)
        self.assertEqual(out.missing_signals, [])

    def test_trend_only_is_discounted_below_full(self):
        providers = [
            self.FixedProvider(SignalKind.trend_momentum, "t", 100),
            self.FixedProvider(SignalKind.demand_growth, "v", 0, SignalProvenance.unavailable),
            self.FixedProvider(SignalKind.surge, "s", 0, SignalProvenance.unavailable),
            self.FixedProvider(SignalKind.absolute_demand, "d", 0, SignalProvenance.unavailable),
            self.FixedProvider(SignalKind.differentiation, "f", 0, SignalProvenance.unavailable),
        ]
        ranker = OpportunityRanker(providers)
        out = ranker.score_one(NicheCandidate(keyword="x"))
        # Only trend (weight 0.20) usable -> coverage 0.20 -> heavy discount.
        # composite=100, discounted = 100*(0.4+0.6*0.2)=52.
        self.assertLess(out.score, 55)
        self.assertIn("demand_growth", out.missing_signals)
        self.assertIn("surge", out.missing_signals)

    def test_rank_orders_by_score(self):
        good = [self.FixedProvider(k, k.value, 90) for k in SignalKind]
        weak = [self.FixedProvider(k, k.value, 20) for k in SignalKind]
        # Build two rankers won't share; instead vary by keyword via one ranker
        ranker = OpportunityRanker(good)
        results = ranker.rank([NicheCandidate(keyword="a"), NicheCandidate(keyword="b")])
        self.assertEqual(results[0].rank, 1)
        self.assertEqual(results[1].rank, 2)
        self.assertGreaterEqual(results[0].score, results[1].score)
        # weak providers produce a lower score than good
        weak_ranker = OpportunityRanker(weak)
        weak_out = weak_ranker.score_one(NicheCandidate(keyword="a"))
        self.assertLess(weak_out.score, results[0].score)


class NoiseFilterTest(unittest.TestCase):
    def test_brand_and_intent_noise_dropped(self):
        from crossborder.opportunity.discover import _is_sellable_niche

        index = StubIndex(_pool(), _digest())
        # intent noise token
        self.assertFalse(_is_sellable_niche("neck massager reviews", index))
        # not in catalog
        self.assertFalse(_is_sellable_niche("artuvate gadget", index))
        # real catalog-backed niche
        self.assertTrue(_is_sellable_niche("good niche", index))


class DeepDiveIntegrationTest(unittest.TestCase):
    """Runs the real mode-1 deep-dive when the dataset is present."""

    def test_deep_dive_on_real_data(self):
        meta = ROOT / "data" / "amazon_reviews_2023" / "meta_Health_and_Personal_Care.jsonl"
        if not meta.exists():
            self.skipTest("Amazon dataset not downloaded")
        from crossborder.opportunity.pipeline import deep_dive

        out = deep_dive("neck massager")
        self.assertEqual(out["selected_keyword"], "neck massager")
        self.assertIn(out["research"]["decision"], {"pass", "requires_revision", "requires_human_review", "blocked"})
        self.assertIn("price_coverage", out["intake_report"])


if __name__ == "__main__":
    unittest.main()
