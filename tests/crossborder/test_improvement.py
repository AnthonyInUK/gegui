from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crossborder.improvement import build_improvement_spec  # noqa: E402
from crossborder.schemas import ReviewPainPoint  # noqa: E402
from crossborder.tools_agent.improvement_tool import run_improvement_tool  # noqa: E402


class ImprovementSpecTest(unittest.TestCase):
    def test_build_spec_orders_requirements_and_keeps_evidence(self):
        pain_points = [
            ReviewPainPoint(
                topic="battery",
                frequency=3,
                severity=2,
                example="Battery died after one hour.",
                source_asins=["BATT1"],
            ),
            ReviewPainPoint(
                topic="durability",
                frequency=10,
                severity=5,
                example="It broke after a week.",
                source_asins=["DURA1", "DURA2"],
            ),
        ]

        spec = build_improvement_spec(
            pain_points,
            product_title="Portable massager",
            keyword="neck massager",
        )

        self.assertEqual(spec.requirements[0].pain_topic, "durability")
        self.assertEqual(spec.requirements[0].priority, "high")
        self.assertEqual(spec.requirements[0].evidence_quote, "It broke after a week.")
        self.assertEqual(spec.requirements[1].pain_topic, "battery")
        self.assertEqual(spec.requirements[1].priority, "low")
        self.assertTrue(spec.differentiation_bullets)
        self.assertIn("durable", spec.emphasis_keywords)
        self.assertIn("合规引擎", spec.honesty_note)

    def test_candidate_bullets_avoid_high_risk_claims(self):
        pain_points = [
            ReviewPainPoint(topic="durability", frequency=10, severity=5),
            ReviewPainPoint(topic="battery", frequency=4, severity=4),
            ReviewPainPoint(topic="odor", frequency=4, severity=3),
        ]

        spec = build_improvement_spec(pain_points)
        joined = " ".join(spec.differentiation_bullets).lower()

        forbidden = {"unbreakable", "lasts forever", "cure", "guaranteed", "100%"}
        self.assertFalse(any(term in joined for term in forbidden))

    def test_unknown_topic_uses_fallback(self):
        spec = build_improvement_spec(
            [ReviewPainPoint(topic="unknown issue", frequency=2, severity=2)]
        )

        self.assertEqual(spec.requirements[0].priority, "low")
        self.assertIn("针对该痛点", spec.requirements[0].requirement)
        self.assertEqual(
            spec.differentiation_bullets,
            ["Designed to address common buyer complaints"],
        )


class ImprovementToolTest(unittest.TestCase):
    def test_tool_success_returns_envelope(self):
        out = run_improvement_tool(
            {
                "workflow_id": "wf_test",
                "seller_id": "seller_test",
                "product_title": "Cable organizer",
                "keyword": "cable organizer",
                "pain_points": [
                    {
                        "topic": "adhesive",
                        "frequency": 8,
                        "severity": 4,
                        "example": "The adhesive falls off.",
                        "source_asins": ["A1"],
                    }
                ],
            }
        )

        self.assertEqual(out.decision, "pass")
        self.assertFalse(out.human_review_required)
        self.assertEqual(out.audit.tool_name, "crossborder.improvement")
        self.assertEqual(out.audit.workflow_id, "wf_test")
        self.assertEqual(out.result["requirements"][0]["pain_topic"], "adhesive")

    def test_tool_empty_pain_points_requires_human_review(self):
        out = run_improvement_tool({})

        self.assertEqual(out.decision, "requires_human_review")
        self.assertTrue(out.human_review_required)
        self.assertIn("无评论痛点", out.result["honesty_note"])

    def test_tool_invalid_input_returns_structured_error(self):
        out = run_improvement_tool({"pain_points": "bad"})

        self.assertEqual(out.decision, "failed")
        self.assertTrue(out.human_review_required)
        self.assertTrue(out.errors)
        self.assertEqual(out.errors[0].code, "invalid_input")


class ImprovementIntegrationTest(unittest.TestCase):
    def test_deep_dive_returns_improvement_spec_when_dataset_exists(self):
        meta = ROOT / "data" / "amazon_reviews_2023" / "meta_Health_and_Personal_Care.jsonl"
        if not meta.exists():
            self.skipTest("Amazon dataset not downloaded")

        from crossborder.opportunity.pipeline import deep_dive

        out = deep_dive("neck massager")

        self.assertIn("improvement_spec", out)
        self.assertTrue(out["improvement_spec"]["requirements"])
        self.assertIn("honesty_note", out["improvement_spec"])

    def test_http_tool_endpoint(self):
        try:
            from fastapi.testclient import TestClient
            from web.app import app
        except Exception as exc:  # pragma: no cover - environment guard
            self.skipTest(f"FastAPI TestClient unavailable: {exc}")

        client = TestClient(app)
        response = client.post(
            "/tools/crossborder/improvement",
            json={
                "pain_points": [
                    {"topic": "installation", "frequency": 5, "severity": 3}
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["decision"], "pass")
        self.assertEqual(data["audit"]["tool_name"], "crossborder.improvement")


if __name__ == "__main__":
    unittest.main()
