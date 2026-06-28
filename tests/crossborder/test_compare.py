from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crossborder.opportunity.compare import _assemble_comparison, compare_niches  # noqa: E402


def _summary(
    keyword: str,
    score: int | None,
    breakdown: dict[str, int] | None = None,
    *,
    confidence: float = 0.8,
    price_coverage: float = 0.8,
    error: str | None = None,
) -> dict:
    return {
        "keyword": keyword,
        "decision": "pass" if error is None else "no_data",
        "score": score,
        "confidence": confidence,
        "score_breakdown": breakdown or {},
        "price_coverage": price_coverage,
        "human_review_required": False,
        "top_pains": [],
        "competitors": 10,
        "error": error,
    }


class CompareAssembleTest(unittest.TestCase):
    def test_assemble_comparison_selects_winner_and_best_per_dimension(self):
        summaries = [
            _summary(
                "neck massager",
                76,
                {
                    "demand": 80,
                    "profitability": 50,
                    "competition": 70,
                    "logistics": 85,
                    "compliance": 90,
                },
            ),
            _summary(
                "foot massager",
                81,
                {
                    "demand": 70,
                    "profitability": 88,
                    "competition": 65,
                    "logistics": 70,
                    "compliance": 86,
                },
            ),
            _summary(
                "cable organizer",
                68,
                {
                    "demand": 55,
                    "profitability": 80,
                    "competition": 90,
                    "logistics": 96,
                    "compliance": 95,
                },
            ),
        ]

        out = _assemble_comparison(summaries)

        self.assertEqual(out["winner"], "foot massager")
        self.assertEqual(out["best_per_dim"]["demand"], "neck massager")
        self.assertEqual(out["best_per_dim"]["profitability"], "foot massager")
        self.assertEqual(out["best_per_dim"]["competition"], "cable organizer")
        self.assertEqual(out["best_per_dim"]["logistics"], "cable organizer")
        self.assertEqual(out["best_per_dim"]["compliance"], "cable organizer")
        self.assertEqual(len(out["radar"]["series"]), 3)

    def test_error_summary_is_excluded_from_winner_and_radar(self):
        out = _assemble_comparison(
            [
                _summary("good", 72, {"demand": 70}),
                _summary("bad", None, error="ValueError: no rows"),
            ]
        )

        self.assertEqual(out["winner"], "good")
        self.assertEqual(len(out["radar"]["series"]), 1)
        self.assertEqual(out["radar"]["series"][0]["keyword"], "good")

    def test_notes_flag_close_scores_and_low_price_coverage(self):
        out = _assemble_comparison(
            [
                _summary("a", 80, {"demand": 80}, price_coverage=0.2),
                _summary("b", 77, {"demand": 77}, price_coverage=0.9),
            ]
        )

        joined = " ".join(out["notes"])
        self.assertIn("利润维度已降级", joined)
        self.assertIn("人工定夺", joined)


class CompareIntegrationTest(unittest.TestCase):
    def test_compare_niches_handles_missing_keyword_when_dataset_exists(self):
        meta = ROOT / "data" / "amazon_reviews_2023" / "meta_Health_and_Personal_Care.jsonl"
        if not meta.exists():
            self.skipTest("Amazon dataset not downloaded")

        out = compare_niches(["neck massager", "electric neck massager", "zzzznope"])

        self.assertEqual(out["keywords"], ["neck massager", "electric neck massager", "zzzznope"])
        self.assertEqual(len(out["niches"]), 3)
        self.assertIsNotNone(out["comparison"]["winner"])
        self.assertIsNone(out["niches"][0]["error"])
        self.assertIsNone(out["niches"][1]["error"])
        self.assertIsNotNone(out["niches"][2]["error"])

    def test_http_compare_endpoint_and_empty_keywords(self):
        try:
            from fastapi.testclient import TestClient
            from web.app import app
        except Exception as exc:  # pragma: no cover - environment guard
            self.skipTest(f"FastAPI TestClient unavailable: {exc}")

        client = TestClient(app)
        bad = client.post("/api/opportunity/compare", json={"keywords": []})
        self.assertEqual(bad.status_code, 400)

        response = client.post(
            "/api/opportunity/compare",
            json={"keywords": ["zzzznope"]},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["keywords"], ["zzzznope"])
        self.assertIsNone(data["comparison"]["winner"])
        self.assertIsNotNone(data["niches"][0]["error"])


if __name__ == "__main__":
    unittest.main()
