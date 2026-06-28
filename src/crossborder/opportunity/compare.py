"""Compare multiple opportunity niches side by side.

The deep-dive pipeline already scores one niche across demand, profitability,
competition, logistics, and compliance. This module composes several deep-dive
outputs into a scorecard for sourcing decisions without changing the scoring
model itself.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from crossborder.opportunity.dataset_index import DEFAULT_META, DEFAULT_REVIEWS
from crossborder.opportunity.pipeline import deep_dive

DIMENSIONS = ["demand", "profitability", "competition", "logistics", "compliance"]


def compare_niches(
    keywords: list[str],
    *,
    target_price: float | None = None,
    meta_path: Path = DEFAULT_META,
    review_path: Path = DEFAULT_REVIEWS,
) -> dict[str, Any]:
    selected = _dedupe_keywords(keywords)[:4]
    summaries: list[dict[str, Any]] = []
    for keyword in selected:
        try:
            dd = deep_dive(
                keyword,
                target_price=target_price,
                meta_path=meta_path,
                review_path=review_path,
            )
            summaries.append(_summarize(keyword, dd))
        except Exception as exc:
            summaries.append(
                {
                    "keyword": keyword,
                    "decision": "no_data",
                    "score": None,
                    "confidence": 0.0,
                    "score_breakdown": {},
                    "price_coverage": None,
                    "human_review_required": True,
                    "top_pains": [],
                    "competitors": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return {
        "keywords": selected,
        "niches": summaries,
        "comparison": _assemble_comparison(summaries),
    }


def _summarize(keyword: str, dd: dict[str, Any]) -> dict[str, Any]:
    research = dd.get("research") or {}
    intake = dd.get("intake_report") or {}
    pains = dd.get("pain_points") or []
    return {
        "keyword": keyword,
        "decision": research.get("decision"),
        "score": research.get("score"),
        "confidence": research.get("confidence"),
        "score_breakdown": research.get("score_breakdown", {}),
        "price_coverage": intake.get("price_coverage"),
        "human_review_required": research.get("human_review_required"),
        "top_pains": [p.get("topic") for p in pains[:3]],
        "competitors": intake.get("generated_competitors", 0),
        "error": None,
    }


def _assemble_comparison(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [
        s
        for s in summaries
        if s.get("error") is None and s.get("score") is not None
    ]
    best_per_dim = {
        dim: max(valid, key=lambda s, d=dim: (s.get("score_breakdown") or {}).get(d, 0))["keyword"]
        if valid
        else None
        for dim in DIMENSIONS
    }
    winner = (
        max(valid, key=lambda s: (s.get("score") or 0, s.get("confidence") or 0))["keyword"]
        if valid
        else None
    )
    radar = {
        "dimensions": DIMENSIONS,
        "series": [
            {
                "keyword": s["keyword"],
                "values": [(s.get("score_breakdown") or {}).get(dim, 0) for dim in DIMENSIONS],
            }
            for s in valid
        ],
    }
    notes: list[str] = []
    if any((s.get("price_coverage") or 1) < 0.25 for s in valid):
        notes.append("部分赛道价格覆盖不足、利润维度已降级，横评利润分偏保守。")
    if len(valid) >= 2:
        top2 = sorted((s.get("score") or 0 for s in valid), reverse=True)[:2]
        if top2[0] - top2[1] <= 5:
            notes.append("Top 赛道分差≤5，建议结合改良空间和采购成本人工定夺。")
    return {
        "dimensions": DIMENSIONS,
        "best_per_dim": best_per_dim,
        "winner": winner,
        "radar": radar,
        "notes": notes,
    }


def _dedupe_keywords(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for keyword in keywords:
        clean = str(keyword or "").strip()
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare opportunity niches with a five-dimension scorecard.")
    parser.add_argument("keywords", nargs="+")
    parser.add_argument("--target-price", type=float, default=None)
    args = parser.parse_args()
    result = compare_niches(args.keywords, target_price=args.target_price)
    comparison = result["comparison"]
    print(f"Winner: {comparison['winner'] or 'none'}")
    print()
    header = ["dimension", *result["keywords"]]
    rows = [header]
    for dim in DIMENSIONS:
        row = [dim]
        for niche in result["niches"]:
            score = (niche.get("score_breakdown") or {}).get(dim)
            row.append("-" if score is None else str(score))
        rows.append(row)
    rows.append(["total_score", *["-" if n.get("score") is None else str(n.get("score")) for n in result["niches"]]])
    width = [max(len(row[i]) for row in rows) for i in range(len(header))]
    for row in rows:
        print("  ".join(value.ljust(width[i]) for i, value in enumerate(row)))
    if comparison["notes"]:
        print("\nNotes:")
        for note in comparison["notes"]:
            print(f"- {note}")
    errors = [n for n in result["niches"] if n.get("error")]
    if errors:
        print("\nErrors:")
        for item in errors:
            print(f"- {item['keyword']}: {item['error']}")


if __name__ == "__main__":
    main()
