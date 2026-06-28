from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from crossborder.data_intake.amazon_reviews_2023_loader import (  # noqa: E402
    build_product_research_request,
    run_loader_and_optionally_research,
)
from crossborder.product_research import research_product  # noqa: E402


FIXTURE_DIR = ROOT / "tests" / "crossborder" / "fixtures" / "amazon_reviews_2023"


class AmazonReviews2023LoaderTest(unittest.TestCase):
    def test_loader_builds_product_research_request(self):
        req = build_product_research_request(
            meta_path=FIXTURE_DIR / "meta_sample.jsonl",
            review_path=FIXTURE_DIR / "review_sample.jsonl",
            keyword="cable organizer",
            category="Office Products",
            unit_cost=4.2,
            max_competitors=5,
        )

        self.assertEqual(req.platform.value, "amazon")
        self.assertGreaterEqual(len(req.competitors), 2)
        self.assertTrue(any(point.topic == "adhesive" for point in req.pain_points))
        self.assertIsNotNone(req.cost_model)
        self.assertIsNotNone(req.data_intake_report)
        self.assertEqual(req.data_intake_report.generated_competitors, len(req.competitors))
        self.assertIn("estimated_monthly_sales_from_review_count", req.data_intake_report.inferred_fields)
        self.assertEqual(req.metadata["source"], "amazon_reviews_2023_public_jsonl")

    def test_loader_output_can_feed_product_research_v2(self):
        req = build_product_research_request(
            meta_path=FIXTURE_DIR / "meta_sample.jsonl",
            review_path=FIXTURE_DIR / "review_sample.jsonl",
            keyword="cable organizer",
            category="Office Products",
            unit_cost=4.2,
            max_competitors=5,
        )
        result = research_product(req)

        self.assertIn(result.decision, {"pass", "requires_revision"})
        self.assertEqual(result.audit["version"], "product-research-v2")
        self.assertGreater(result.score_breakdown["demand"], 50)
        self.assertGreaterEqual(len(result.candidate_ranking), 2)
        self.assertEqual(result.candidate_ranking[0]["role"], "selected")
        self.assertTrue(result.selection_rationale)
        self.assertTrue(any(step["step"] == "candidate_ranking" for step in result.research_pipeline))

    def test_loader_can_return_research_bundle(self):
        payload = run_loader_and_optionally_research(
            meta_path=FIXTURE_DIR / "meta_sample.jsonl",
            review_path=FIXTURE_DIR / "review_sample.jsonl",
            keyword="cable organizer",
            category="Office Products",
            unit_cost=4.2,
            max_competitors=5,
            run_research=True,
        )

        self.assertIn("request", payload)
        self.assertIn("research_result", payload)
        self.assertEqual(payload["research_result"]["audit"]["version"], "product-research-v2")


if __name__ == "__main__":
    unittest.main()
