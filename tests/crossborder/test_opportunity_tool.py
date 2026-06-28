from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crossborder.tools_agent.contracts import ToolDecision  # noqa: E402
from crossborder.tools_agent.opportunity_tool import run_opportunity_tool  # noqa: E402


class OpportunityToolTest(unittest.TestCase):
    def test_empty_seed_returns_validation_error_envelope(self):
        envelope = run_opportunity_tool({"seed_keyword": ""})

        self.assertEqual(envelope.decision, ToolDecision.failed.value)
        self.assertTrue(envelope.human_review_required)
        self.assertTrue(envelope.errors)
        self.assertEqual(envelope.errors[0].code, "invalid_input")
        self.assertEqual(envelope.audit.tool_name, "crossborder.opportunity")
        self.assertTrue(envelope.audit.input_hash)

    def test_missing_seed_returns_validation_error_envelope(self):
        envelope = run_opportunity_tool({})

        self.assertEqual(envelope.decision, ToolDecision.failed.value)
        self.assertTrue(envelope.human_review_required)
        self.assertTrue(envelope.errors)
        self.assertEqual(envelope.errors[0].code, "invalid_input")

    def test_success_path_on_real_dataset_returns_compact_result(self):
        meta = ROOT / "data" / "amazon_reviews_2023" / "meta_Health_and_Personal_Care.jsonl"
        if not meta.exists():
            self.skipTest("Amazon dataset not downloaded")

        envelope = run_opportunity_tool({"seed_keyword": "neck massager", "max_candidates": 3})

        allowed = {item.value for item in ToolDecision}
        self.assertIn(envelope.decision, allowed)
        self.assertEqual(envelope.audit.tool_name, "crossborder.opportunity")
        self.assertTrue(envelope.audit.input_hash)
        self.assertIn("selected_keyword", envelope.result)
        self.assertIn("top_opportunities", envelope.result)
        self.assertNotIn("competitors", envelope.result)
        self.assertNotIn("research_pipeline", envelope.result)


if __name__ == "__main__":
    unittest.main()
