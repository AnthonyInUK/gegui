from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.demo_crossborder_pipeline import _pretty_summary, run_demo_pipeline  # noqa: E402


class DemoCrossBorderPipelineTest(unittest.TestCase):
    def test_demo_pipeline_runs_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "demo_pipeline_result.json"
            report = run_demo_pipeline(output_path=output_path)

        self.assertEqual(report["demo"]["name"], "crossborder_agent_end_to_end_demo")
        self.assertIn("data_intake", report["stages"])
        self.assertIn("product_research", report["stages"])
        self.assertIn("listing_generation", report["stages"])
        self.assertIn("compliance_check", report["stages"])
        self.assertIn("ads_diagnostic", report["stages"])
        self.assertIn("customer_service", report["stages"])
        self.assertEqual(report["stages"]["product_research"]["decision"], "pass")
        self.assertEqual(report["stages"]["compliance_check"]["decision"], "pass")
        self.assertEqual(report["stages"]["ads_diagnostic"]["decision"], "requires_human_review")
        self.assertEqual(report["stages"]["customer_service"]["decision"], "requires_human_review")
        self.assertGreaterEqual(report["gate_summary"]["total_actions"], 4)
        self.assertGreaterEqual(
            report["gate_summary"]["decision_counts"].get("requires_human_review", 0),
            1,
        )
        self.assertTrue(report["final_summary"]["ready_for_publish"])
        self.assertTrue(report["final_summary"]["human_review_required"])
        self.assertIn("research_id", report["audit_summary"])
        self.assertIn("listing_id", report["audit_summary"])
        self.assertIn("compliance_check_id", report["audit_summary"])
        self.assertGreaterEqual(len(report["audit_summary"]["gate_ids"]), 1)

    def test_demo_pipeline_supports_offline_compliance_stub_and_pretty_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "demo_pipeline_result.json"
            report = run_demo_pipeline(output_path=output_path, run_compliance=False)

        self.assertEqual(report["stages"]["compliance_check"]["audit"]["check_id"], "offline_compliance_stub")
        pretty = _pretty_summary(report)
        stage = _pretty_summary(report, "ads_diagnostic")
        self.assertIn("Cross-border Agent Demo", pretty)
        self.assertIn("requires_human_review", stage)


if __name__ == "__main__":
    unittest.main()
