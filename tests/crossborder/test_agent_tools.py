from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from crossborder.tools_agent.ads_diagnostic_tool import run_ads_diagnostic_tool  # noqa: E402
from crossborder.tools_agent.listing_generation_tool import run_listing_generation_tool  # noqa: E402
from crossborder.tools_agent.product_research_tool import run_product_research_tool  # noqa: E402

EXAMPLE_DIR = ROOT / "examples" / "crossborder" / "tools"


def _load(name: str) -> dict:
    return json.loads((EXAMPLE_DIR / name).read_text(encoding="utf-8"))


class CrossBorderAgentToolsTest(unittest.TestCase):
    def test_product_research_tool_independent_call(self):
        envelope = run_product_research_tool(_load("product_research_tool.json"))

        self.assertEqual(envelope.decision, "pass")
        self.assertFalse(envelope.errors)
        self.assertGreater(envelope.confidence, 0)
        self.assertIn("score", envelope.result)
        self.assertIn("selected_candidate", envelope.result)
        self.assertIn("candidate_ranking", envelope.result)
        self.assertEqual(envelope.audit.tool_name, "crossborder.product_research")
        self.assertEqual(envelope.audit.workflow_id, "wf_tool_product_research_demo")
        self.assertTrue(envelope.audit.input_hash)

    def test_listing_generation_tool_independent_call(self):
        envelope = run_listing_generation_tool(_load("listing_generation_tool.json"))

        self.assertEqual(envelope.decision, "pass")
        self.assertFalse(envelope.errors)
        self.assertIn("listing", envelope.result)
        self.assertIn("platform_constraints", envelope.result)
        self.assertIn("source_fields_used", envelope.result)
        self.assertLessEqual(
            len(envelope.result["listing"]["title"]),
            envelope.result["platform_constraints"]["title_limit"],
        )
        self.assertEqual(envelope.audit.tool_name, "crossborder.listing_generation")
        self.assertTrue(envelope.audit.trace_id.startswith("lst_"))

    def test_ads_diagnostic_tool_independent_call_and_gates_high_risk_actions(self):
        envelope = run_ads_diagnostic_tool(_load("ads_diagnostic_tool.json"))

        self.assertEqual(envelope.decision, "requires_human_review")
        self.assertTrue(envelope.human_review_required)
        self.assertFalse(envelope.errors)
        self.assertIn("metrics", envelope.result)
        self.assertIn("gated_actions", envelope.result)
        self.assertTrue(
            any(
                action["gate_decision"] == "requires_human_review"
                for action in envelope.result["gated_actions"]
            )
        )
        self.assertEqual(envelope.audit.tool_name, "crossborder.ads_diagnostic")
        self.assertTrue(envelope.audit.trace_id.startswith("ads_"))

    def test_invalid_input_returns_structured_errors(self):
        envelope = run_product_research_tool(
            {
                "platform": "amazon",
                "market": "US",
                "workflow_id": "wf_invalid",
            }
        )

        self.assertEqual(envelope.decision, "failed")
        self.assertTrue(envelope.human_review_required)
        self.assertTrue(envelope.errors)
        self.assertEqual(envelope.errors[0].code, "invalid_input")
        self.assertEqual(envelope.audit.tool_name, "crossborder.product_research")


if __name__ == "__main__":
    unittest.main()
