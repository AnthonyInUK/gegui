from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crossborder.opportunity.pipeline import deep_dive, discover_to_workflow  # noqa: E402


ALLOWED_STATUSES = {
    "ready_to_publish",
    "needs_revision",
    "needs_human_review",
    "blocked",
    "no_niche",
    "compliance_runtime_unavailable",
}


def _stub_report() -> dict:
    return {
        "seed_keyword": "stub seed",
        "opportunities": [
            {
                "keyword": "desk cable organizer",
                "score": 77.0,
                "rank": 1,
            }
        ],
        "selected_keyword": "desk cable organizer",
        "selected_opportunity": {
            "keyword": "desk cable organizer",
            "score": 77.0,
            "rank": 1,
        },
        "intake_report": None,
        "product": {
            "title": "Reusable Silicone Cable Organizer Clips for Desk",
            "category": "Cable Organizer",
            "brand": "DeskMate",
            "features": [
                "Compact cable clips",
                "Reusable silicone",
                "Easy setup",
            ],
            "claims": [
                "Designed for practical desk cable organization."
            ],
            "materials": [
                "silicone"
            ],
        },
        "competitors": [],
        "pain_points": [],
        "research": None,
        "handoff": [
            "Stub report supplied directly; no network discovery call required."
        ],
    }


class OpportunityToWorkflowTest(unittest.TestCase):
    def test_stub_report_runs_without_network_discovery(self):
        out = discover_to_workflow("ignored seed", report=_stub_report())

        self.assertEqual(out["selected_keyword"], "desk cable organizer")
        self.assertIn("workflow", out)
        self.assertIn("workflow_status", out)
        self.assertIn(out["workflow_status"], ALLOWED_STATUSES)
        self.assertIsInstance(out["workflow"], dict)

    def test_no_niche_returns_without_workflow(self):
        out = discover_to_workflow(
            "empty seed",
            report={
                "seed_keyword": "empty seed",
                "opportunities": [],
                "selected_keyword": None,
                "intake_report": None,
                "research": None,
                "handoff": ["no niche"],
            },
        )

        self.assertIsNone(out["workflow"])
        self.assertEqual(out["workflow_status"], "no_niche")

    def test_dataset_gated_deep_dive_report_can_flow_to_workflow(self):
        meta = ROOT / "data" / "amazon_reviews_2023" / "meta_Health_and_Personal_Care.jsonl"
        if not meta.exists():
            self.skipTest("Amazon dataset not downloaded")

        report = deep_dive("neck massager")
        report.update(
            {
                "seed_keyword": "neck massager",
                "opportunities": [
                    {
                        "keyword": report["selected_keyword"],
                        "score": 70.0,
                        "rank": 1,
                    }
                ],
                "selected_opportunity": {
                    "keyword": report["selected_keyword"],
                    "score": 70.0,
                    "rank": 1,
                },
                "handoff": report.get("handoff") or ["Dataset deep-dive report reused for workflow handoff."],
            }
        )

        out = discover_to_workflow("neck massager", report=report)

        self.assertIn("selected_keyword", out)
        self.assertIn("workflow", out)
        self.assertIn("workflow_status", out)
        self.assertIn(out["workflow_status"], ALLOWED_STATUSES)


if __name__ == "__main__":
    unittest.main()
