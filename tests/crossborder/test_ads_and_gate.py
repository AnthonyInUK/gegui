from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from crossborder.action_gate import evaluate_action_gate  # noqa: E402
from crossborder.ads.diagnostic_agent import diagnose_ads  # noqa: E402
from crossborder.schemas import (  # noqa: E402
    ActionDecision,
    ActionGateRequest,
    AdsDiagnosticRequest,
)


class AdsDiagnosticAndActionGateTest(unittest.TestCase):
    def test_ads_diagnostic_flags_high_acos_and_non_conversion(self):
        req = AdsDiagnosticRequest.model_validate(
            {
                "platform": "amazon",
                "market": "US",
                "workflow_id": "wf_ads_test",
                "target_acos": 0.3,
                "campaigns": [
                    {
                        "campaign_id": "cmp_1",
                        "impressions": 5000,
                        "clicks": 80,
                        "spend": 80,
                        "sales": 100,
                        "orders": 3,
                        "units": 3,
                    },
                    {
                        "campaign_id": "cmp_2",
                        "impressions": 3000,
                        "clicks": 40,
                        "spend": 40,
                        "sales": 0,
                        "orders": 0,
                        "units": 0,
                    },
                ],
            }
        )

        result = diagnose_ads(req)

        self.assertEqual(result.decision, "requires_human_review")
        self.assertGreater(result.metrics["acos"], req.target_acos)
        self.assertTrue(any(issue["category"] == "high_acos" for issue in result.issues))
        self.assertTrue(result.human_review_required)
        self.assertTrue(result.gated_actions)
        self.assertTrue(any(action["gate_decision"] == "requires_human_review" for action in result.gated_actions))
        self.assertFalse(any(action["allowed"] for action in result.gated_actions if action["action_type"] == "pause_campaign"))

    def test_ads_diagnostic_passes_healthy_campaign(self):
        req = AdsDiagnosticRequest.model_validate(
            {
                "campaigns": [
                    {
                        "campaign_id": "cmp_1",
                        "impressions": 2000,
                        "clicks": 80,
                        "spend": 40,
                        "sales": 240,
                        "orders": 12,
                        "units": 12,
                    }
                ]
            }
        )

        result = diagnose_ads(req)

        self.assertEqual(result.decision, "pass")
        self.assertEqual(result.risk_level, "low")
        self.assertEqual(result.gated_actions[0]["action_type"], "monitor_campaign")
        self.assertTrue(result.gated_actions[0]["allowed"])

    def test_action_gate_requires_human_for_price_change(self):
        result = evaluate_action_gate(
            ActionGateRequest(
                action_type="change_price",
                actor_agent="AdsAgent",
                workflow_id="wf_gate",
                permissions=["pricing"],
                risk_level="medium",
            )
        )

        self.assertEqual(result.decision, ActionDecision.requires_human_review)
        self.assertFalse(result.allowed)

    def test_action_gate_allows_low_risk_ads_manage_action(self):
        result = evaluate_action_gate(
            ActionGateRequest(
                action_type="add_negative_keyword",
                actor_agent="AdsAgent",
                permissions=["ads_manage"],
                risk_level="low",
            )
        )

        self.assertEqual(result.decision, ActionDecision.allowed)
        self.assertTrue(result.allowed)

    def test_action_gate_blocks_autonomous_appeal(self):
        result = evaluate_action_gate(
            ActionGateRequest(
                action_type="submit_appeal",
                actor_agent="ComplianceAgent",
                permissions=["appeal"],
                risk_level="high",
            )
        )

        self.assertEqual(result.decision, ActionDecision.blocked)
        self.assertFalse(result.allowed)


if __name__ == "__main__":
    unittest.main()
