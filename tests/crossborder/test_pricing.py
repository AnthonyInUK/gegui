from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crossborder.pricing.inject import deep_dive_with_prices, inject_real_prices  # noqa: E402
from crossborder.pricing.providers import (  # noqa: E402
    KeepaPriceProvider,
    ManualPriceProvider,
    PriceProvenance,
    StubPriceProvider,
)
from crossborder.product_research import _price_coverage  # noqa: E402
from crossborder.schemas import CompetitorSnapshot, ProductBrief, ProductResearchRequest  # noqa: E402


class PricingProviderTest(unittest.TestCase):
    def test_stub_price_provider_is_deterministic(self):
        provider = StubPriceProvider()
        first = provider.fetch_price("B0STUB")
        second = provider.fetch_price("B0STUB")

        self.assertEqual(first.price, second.price)
        self.assertEqual(first.provenance, PriceProvenance.stub)
        self.assertGreaterEqual(first.price, 15)
        self.assertLessEqual(first.price, 75)

    def test_manual_price_provider_hits_and_misses(self):
        path = ROOT / "tests" / "crossborder" / "fixtures" / "_manual_prices.json"
        path.write_text(json.dumps({"B0KNOWN": 29.99}), encoding="utf-8")
        try:
            provider = ManualPriceProvider(path)
            hit = provider.fetch_price("B0KNOWN")
            miss = provider.fetch_price("B0UNKNOWN")
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(hit.price, 29.99)
        self.assertEqual(hit.provenance, PriceProvenance.manual)
        self.assertIsNone(miss.price)
        self.assertEqual(miss.provenance, PriceProvenance.unavailable)

    def test_keepa_without_api_key_is_unavailable(self):
        previous = os.environ.pop("KEEPA_API_KEY", None)
        try:
            provider = KeepaPriceProvider(api_key=None)
            quote = provider.fetch_price("B0ANY")
        finally:
            if previous is not None:
                os.environ["KEEPA_API_KEY"] = previous

        self.assertIsNone(quote.price)
        self.assertEqual(quote.provenance, PriceProvenance.unavailable)


class PricingInjectionTest(unittest.TestCase):
    def test_inject_real_prices_sets_top_missing_prices_and_target_price(self):
        req = ProductResearchRequest(
            product=ProductBrief(title="Desk Cable Organizer", category="Office Products"),
            competitors=[
                CompetitorSnapshot(asin="A1", title="A1", review_count=500, price=None),
                CompetitorSnapshot(asin="A2", title="A2", review_count=300, price=None),
                CompetitorSnapshot(asin="A3", title="A3", review_count=100, price=None),
            ],
        )

        updated, quotes = inject_real_prices(req, StubPriceProvider(), top_n=2, unit_cost=5.0)

        self.assertEqual(len(quotes), 2)
        self.assertGreater(_price_coverage(updated), _price_coverage(req))
        self.assertEqual(sum(1 for item in updated.competitors if item.price is not None), 2)
        self.assertIsNotNone(updated.target_price)
        self.assertIsNotNone(updated.cost_model)
        self.assertEqual(updated.cost_model.unit_cost, 5.0)

    def test_dataset_gated_deep_dive_with_prices(self):
        meta = ROOT / "data" / "amazon_reviews_2023" / "meta_Health_and_Personal_Care.jsonl"
        if not meta.exists():
            self.skipTest("Amazon dataset not downloaded")

        report = deep_dive_with_prices("neck massager", StubPriceProvider(), unit_cost=8.0)

        self.assertIn("before", report)
        self.assertIn("after", report)
        self.assertIn("price_quotes", report)
        self.assertGreaterEqual(report["coverage_after"], report["coverage_before"])


if __name__ == "__main__":
    unittest.main()
