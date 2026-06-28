from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from crossborder.listing_agent import generate_listing, generate_listing_tool  # noqa: E402
from crossborder.contracts.agent_tool import AgentRuntime, AgentToolResult  # noqa: E402
from crossborder.product_research import research_product  # noqa: E402
from crossborder.schemas import (  # noqa: E402
    CrossBorderRequest,
    ListingGenerationRequest,
    Platform,
    ProductResearchRequest,
    WorkflowStatus,
)
from crossborder.workflow import run_workflow  # noqa: E402


def _req(platform: str = "amazon", **product_overrides) -> CrossBorderRequest:
    product = {
        "title": "Portable Neck Massager",
        "category": "health_personal_care",
        "brand": "DemoBrand",
        "features": ["portable design", "quiet operation", "gentle heat"],
        "claims": ["supports everyday muscle relaxation"],
        "materials": ["ABS", "silicone"],
        "audience": "home users",
        **product_overrides,
    }
    return CrossBorderRequest.model_validate(
        {
            "platform": platform,
            "market": "US",
            "workflow_id": f"wf_{platform}",
            "seller_id": "seller_demo",
            "product": product,
        }
    )


def _compliance(decision: str, suggested_rewrite: dict | None = None) -> dict:
    return {
        "decision": decision,
        "risk_level": "low" if decision == "pass" else "medium",
        "confidence": 1.0,
        "issues": [],
        "suggested_rewrite": suggested_rewrite or {},
        "human_review_required": decision == "requires_human_review",
        "audit": {"check_id": f"chk_{decision}"},
    }


class CrossBorderWorkflowTest(unittest.TestCase):
    def test_amazon_low_risk_ready_to_publish(self):
        with patch("crossborder.workflow.check_listing_compliance", return_value=_compliance("pass")):
            result = run_workflow(_req())

        self.assertEqual(result.status, WorkflowStatus.ready_to_publish)
        self.assertEqual(result.compliance_check_id, "chk_pass")
        self.assertTrue(result.listing_package.ready)
        self.assertLessEqual(len(result.listing.title), 180)
        self.assertLessEqual(len(result.listing.bullets), 5)
        self.assertEqual(
            [stage["name"] for stage in result.stage_results[:6]],
            [
                "intake",
                "product_research",
                "category",
                "listing",
                "platform_rules",
                "assets",
            ],
        )

    def test_revision_attempt_runs_once(self):
        checks = [
            _compliance("requires_revision", {"ad_copy": "Designed for everyday relaxation."}),
            _compliance("requires_revision", {"ad_copy": "Still needs review."}),
        ]
        with patch("crossborder.workflow.check_listing_compliance", side_effect=checks):
            result = run_workflow(_req(), max_revision_attempts=1)

        self.assertEqual(result.status, WorkflowStatus.needs_revision)
        self.assertEqual(result.revision_attempts, 1)
        self.assertIn("Designed for everyday relaxation.", result.listing.description)
        self.assertEqual(
            [stage["name"] for stage in result.stage_results].count("rewrite"),
            1,
        )

    def test_human_review_routes_to_human_queue(self):
        with patch(
            "crossborder.workflow.check_listing_compliance",
            return_value=_compliance("requires_human_review"),
        ):
            result = run_workflow(_req())

        self.assertEqual(result.status, WorkflowStatus.needs_human_review)
        self.assertEqual(result.revision_attempts, 0)

    def test_temu_and_walmart_generate_basic_listing(self):
        for platform in ("temu", "walmart"):
            listing = generate_listing(_req(platform).product, Platform(platform))
            self.assertTrue(listing.title)
            self.assertTrue(listing.bullets)

    def test_listing_generation_tool_returns_audited_result(self):
        result = generate_listing_tool(
            ListingGenerationRequest(
                platform=Platform.amazon,
                product=_req().product,
                workflow_id="wf_listing_tool",
                keyword_hints=["neck relaxer"],
            )
        )

        self.assertEqual(result.decision, "pass")
        self.assertTrue(result.listing.title)
        self.assertIn("neck relaxer", result.listing.search_terms)
        self.assertEqual(result.audit["tool"], "crossborder.listing.generate")

    def test_listing_generation_tool_flags_thin_input(self):
        result = generate_listing_tool(
            ListingGenerationRequest(
                platform=Platform.amazon,
                product={
                    "title": "Generic Product",
                    "category": "home",
                },
            )
        )

        self.assertEqual(result.decision, "requires_human_review")
        self.assertTrue(result.human_review_required)
        self.assertEqual(result.issues[0]["category"], "thin_product_input")

    def test_image_urls_are_preserved_for_compliance_adapter(self):
        captured = {}

        def fake_run_compliance_check(req):
            captured["image_urls"] = req.content.image_urls
            return type(
                "Response",
                (),
                {"model_dump": lambda self, mode="json": _compliance("pass")},
            )()

        with patch("crossborder.tools.run_compliance_check", side_effect=fake_run_compliance_check):
            from crossborder.tools import check_listing_compliance

            req = _req(image_urls=["https://example.com/product.png"])
            listing = generate_listing(req.product, req.platform)
            check_listing_compliance(req, listing)

        self.assertEqual(captured["image_urls"], ["https://example.com/product.png"])

    def test_image_urls_are_preserved_in_listing_package(self):
        with patch("crossborder.workflow.check_listing_compliance", return_value=_compliance("pass")):
            result = run_workflow(_req(image_urls=["https://example.com/product.png"]))

        self.assertEqual(result.listing.image_urls, ["https://example.com/product.png"])
        self.assertEqual(result.listing_package.listing.image_urls, ["https://example.com/product.png"])

    def test_marketplace_preflight_flags_medical_claim_after_compliance_pass(self):
        with patch(
            "crossborder.tools.run_compliance_check",
            return_value=type(
                "Response",
                (),
                {"model_dump": lambda self, mode="json": _compliance("pass")},
            )(),
        ):
            from crossborder.tools import check_listing_compliance

            req = _req(claims=["relieves chronic pain"])
            listing = generate_listing(req.product, req.platform)
            compliance = check_listing_compliance(req, listing)

        self.assertEqual(compliance["decision"], "requires_revision")
        self.assertIn("marketplace_claim_preflight", compliance["risk_categories"])

    def test_agent_tool_contract_accepts_mixed_runtime_result(self):
        result = AgentToolResult(
            tool_name="listing.generate",
            runtime=AgentRuntime.openai_agents_sdk,
            artifacts={"title": "Demo"},
        )

        self.assertEqual(result.decision.value, "pass")
        self.assertEqual(result.runtime, AgentRuntime.openai_agents_sdk)

    def test_product_research_scores_strong_candidate(self):
        req = ProductResearchRequest.model_validate(
            {
                "platform": "amazon",
                "market": "US",
                "workflow_id": "wf_research_good",
                "seller_id": "seller_demo",
                "product": {
                    "title": "Silicone Cable Organizer",
                    "category": "home_office",
                    "features": ["compact", "reusable", "easy setup"],
                    "claims": ["keeps desk cables tidy"],
                    "materials": ["silicone"],
                    "attributes": {"weight_kg": 0.1},
                },
                "target_price": 19.99,
                "landed_cost": 6.0,
                "monthly_search_volume": 18000,
                "competitor_count": 45,
                "avg_rating": 4.1,
                "review_pain_points": ["adhesive falls off", "too bulky"],
            }
        )

        result = research_product(req)

        self.assertEqual(result.decision, "pass")
        self.assertGreaterEqual(result.score, 70)
        self.assertEqual(result.audit["tool"], "crossborder.product_research")

    def test_product_research_routes_risky_medical_candidate_to_human(self):
        req = ProductResearchRequest.model_validate(
            {
                "platform": "amazon",
                "market": "US",
                "product": {
                    "title": "Pain Relief Therapy Device",
                    "category": "health_personal_care",
                    "claims": ["treat chronic pain"],
                    "attributes": {"battery": True, "weight_kg": 0.5},
                },
                "target_price": 39.99,
                "landed_cost": 12.0,
                "monthly_search_volume": 12000,
                "competitor_count": 60,
                "avg_rating": 4.3,
            }
        )

        result = research_product(req)

        self.assertIn(result.decision, {"requires_human_review", "blocked"})
        self.assertLess(result.score_breakdown["compliance"], 50)

    def test_product_research_v2_uses_amazon_data_intake(self):
        req = ProductResearchRequest.model_validate(
            {
                "platform": "amazon",
                "market": "US",
                "product": {
                    "title": "Silicone Cable Organizer",
                    "category": "home_office",
                    "features": ["compact", "reusable", "easy setup"],
                    "claims": ["keeps desk cables tidy"],
                    "materials": ["silicone"],
                },
                "target_price": 19.99,
                "competitors": [
                    {
                        "asin": "B000TEST01",
                        "price": 18.99,
                        "rating": 4.2,
                        "review_count": 420,
                        "estimated_monthly_sales": 900,
                        "weaknesses": ["adhesive falls off"],
                    },
                    {
                        "asin": "B000TEST02",
                        "price": 21.99,
                        "rating": 4.0,
                        "review_count": 260,
                        "estimated_monthly_sales": 650,
                        "weaknesses": ["too bulky"],
                    },
                ],
                "pain_points": [
                    {"topic": "adhesive falls off", "frequency": 18, "severity": 4},
                    {"topic": "too bulky", "frequency": 9, "severity": 3},
                ],
                "cost_model": {
                    "unit_cost": 4.2,
                    "inbound_shipping": 0.7,
                    "referral_fee": 3.0,
                    "fulfillment_fee": 3.8,
                    "ads_cpa_estimate": 2.2,
                    "return_cost_allowance": 0.4,
                },
                "logistics": {"weight_kg": 0.12},
                "compliance_precheck": {},
            }
        )

        result = research_product(req)

        self.assertEqual(result.decision, "pass")
        self.assertGreaterEqual(result.score_breakdown["demand"], 80)
        self.assertGreaterEqual(result.score_breakdown["profitability"], 60)
        self.assertEqual(result.audit["version"], "product-research-v2")

    def test_product_research_v2_blocks_ip_risk(self):
        req = ProductResearchRequest.model_validate(
            {
                "platform": "amazon",
                "market": "US",
                "product": {
                    "title": "Brand Compatible Toy Accessory",
                    "category": "toys",
                    "features": ["replacement part"],
                },
                "target_price": 24.99,
                "cost_model": {"unit_cost": 5.0, "fulfillment_fee": 4.5, "referral_fee": 3.7},
                "compliance_precheck": {
                    "trademark_risk": True,
                    "patent_risk": True,
                    "notes": ["Potential branded compatibility claim and design patent risk."],
                },
            }
        )

        result = research_product(req)

        self.assertEqual(result.decision, "blocked")
        self.assertLess(result.score_breakdown["compliance"], 50)
        self.assertTrue(any(issue["category"] == "amazon_compliance_precheck" for issue in result.issues))


if __name__ == "__main__":
    unittest.main()
