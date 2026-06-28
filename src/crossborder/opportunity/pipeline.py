"""Mode 2 -> Mode 1 bridge: discover a niche, then deep-dive it.

The opportunity engine (mode 2) answers "which niche should I enter?" by ranking
keywords. This module takes its #1 ranked niche and hands it to the existing
product-research engine (mode 1), which answers "is this specific niche actually
worth sourcing?" via the 5-dimension score on real Amazon data. Together they
close the loop: keywords are discovered, ranked, then the winner is analyzed in
depth — no hardcoded keyword anywhere.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossborder.data_intake.amazon_reviews_2023_loader import build_product_research_request
from crossborder.improvement import build_improvement_spec
from crossborder.opportunity.dataset_index import DEFAULT_META, DEFAULT_REVIEWS
from crossborder.opportunity.discover import discover
from crossborder.product_research import research_product
from crossborder.schemas import CrossBorderRequest, ProductBrief
from crossborder.workflow import run_workflow


def discover_and_deep_dive(
    seed_keyword: str,
    *,
    max_candidates: int = 8,
    target_price: float | None = None,
    snapshot_path: Path | None = None,
    meta_path: Path = DEFAULT_META,
    review_path: Path = DEFAULT_REVIEWS,
) -> dict[str, Any]:
    """Run mode 2 (discover + rank) then mode 1 (deep dive the winner)."""
    # --- Mode 2: discover and rank niche opportunities ------------------- #
    opportunities = discover(seed_keyword, max_candidates=max_candidates, snapshot_path=snapshot_path)
    if not opportunities:
        return {
            "seed_keyword": seed_keyword,
            "opportunities": [],
            "selected_keyword": None,
            "intake_report": None,
            "research": None,
            "handoff": ["机会引擎未发现可执行赛道（数据集中无足够竞品）。"],
        }

    selected = opportunities[0]

    # --- Mode 1: deep-dive the #1 ranked niche on real data ------------- #
    req = build_product_research_request(
        meta_path=meta_path,
        review_path=review_path,
        keyword=selected.keyword,
        target_price=target_price,
        max_competitors=20,
        max_reviews=20000,
        workflow_id=f"wf_opp_{_slug(selected.keyword)}",
    )
    research = research_product(req)
    improvement_spec = build_improvement_spec(
        req.pain_points,
        product_title=req.product.title,
        keyword=selected.keyword,
    )

    return {
        "seed_keyword": seed_keyword,
        "opportunities": [o.model_dump(mode="json") for o in opportunities],
        "selected_keyword": selected.keyword,
        "selected_opportunity": selected.model_dump(mode="json"),
        "intake_report": req.data_intake_report.model_dump(mode="json")
        if req.data_intake_report
        else None,
        "product": req.product.model_dump(mode="json"),
        "competitors": [c.model_dump(mode="json") for c in req.competitors],
        "pain_points": [p.model_dump(mode="json") for p in req.pain_points],
        "improvement_spec": improvement_spec.model_dump(mode="json"),
        "research": research.model_dump(mode="json"),
        "handoff": _handoff_notes(selected, research, req),
    }


def deep_dive(
    keyword: str,
    *,
    target_price: float | None = None,
    meta_path: Path = DEFAULT_META,
    review_path: Path = DEFAULT_REVIEWS,
) -> dict[str, Any]:
    """Deep-dive one niche on the real dataset (mode 1 only, no Trends call).

    Fast enough to run on demand when a user clicks a different niche in the
    ranking, since it only matches the cached meta index and review digest.
    """
    req = build_product_research_request(
        meta_path=meta_path,
        review_path=review_path,
        keyword=keyword,
        target_price=target_price,
        max_competitors=20,
        max_reviews=20000,
        workflow_id=f"wf_opp_{_slug(keyword)}",
    )
    research = research_product(req)
    improvement_spec = build_improvement_spec(
        req.pain_points,
        product_title=req.product.title,
        keyword=keyword,
    )
    return {
        "selected_keyword": keyword,
        "intake_report": req.data_intake_report.model_dump(mode="json")
        if req.data_intake_report
        else None,
        "product": req.product.model_dump(mode="json"),
        "competitors": [c.model_dump(mode="json") for c in req.competitors],
        "pain_points": [p.model_dump(mode="json") for p in req.pain_points],
        "improvement_spec": improvement_spec.model_dump(mode="json"),
        "research": research.model_dump(mode="json"),
    }


def discover_to_workflow(
    seed_keyword: str,
    *,
    target_price: float | None = None,
    max_candidates: int = 8,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Discover a niche, rebuild its ProductBrief, then run the operating workflow.

    This is the bridge from the opportunity engine to the existing 9-stage
    listing/compliance/publish workflow. Passing an already computed report is
    useful for tests and UI flows that should not trigger a second Trends call.
    """
    out = report or discover_and_deep_dive(
        seed_keyword,
        target_price=target_price,
        max_candidates=max_candidates,
    )
    selected_keyword = out.get("selected_keyword")
    if not selected_keyword:
        return {
            **out,
            "workflow": None,
            "workflow_status": "no_niche",
        }

    product_payload = out.get("product") or {}
    product = ProductBrief.model_validate(product_payload)
    opportunity = out.get("selected_opportunity") or {}
    score = opportunity.get("score")
    req = CrossBorderRequest(
        platform="amazon",
        market="US",
        product=product,
        workflow_id=f"wf_opp_{_slug(str(selected_keyword))}",
        seller_id="seller_opportunity",
        metadata={
            "source": "opportunity_engine",
            "seed_keyword": seed_keyword,
            "selected_keyword": selected_keyword,
            "opportunity_score": score,
        },
    )

    try:
        result = run_workflow(req)
    except ModuleNotFoundError as exc:
        workflow = _workflow_unavailable(req, exc)
        return {
            **out,
            "workflow": workflow,
            "workflow_status": "compliance_runtime_unavailable",
        }
    except Exception as exc:
        if exc.__class__.__name__ != "AssetDownloadError":
            raise
        workflow = _workflow_unavailable(req, exc)
        workflow["status"] = "needs_human_review"
        workflow["compliance"]["risk_level"] = "medium"
        workflow["compliance"]["issues"] = [
            {
                "category": "asset_download_failed",
                "severity": "medium",
                "reason": str(exc),
                "suggestion": "Retry asset download or provide local image/document files.",
            }
        ]
        return {
            **out,
            "workflow": workflow,
            "workflow_status": "needs_human_review",
        }

    return {
        **out,
        "workflow": result.model_dump(mode="json"),
        "workflow_status": result.status.value,
    }


def _workflow_unavailable(req: CrossBorderRequest, exc: Exception) -> dict[str, Any]:
    return {
        "status": "needs_human_review",
        "platform": req.platform.value,
        "market": req.market.value,
        "workflow_id": req.workflow_id,
        "seller_id": req.seller_id,
        "listing": None,
        "listing_package": None,
        "compliance": {
            "decision": "requires_human_review",
            "risk_level": "unknown",
            "confidence": 0.0,
            "risk_categories": ["compliance_runtime_unavailable"],
            "issues": [
                {
                    "category": "compliance_runtime_unavailable",
                    "severity": "medium",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "suggestion": "Install or start the compliance runtime before publishing.",
                }
            ],
            "human_review_required": True,
            "audit": {
                "check_id": "compliance_runtime_unavailable",
                "workflow_id": req.workflow_id,
                "tool_contract_version": "compliance-tool-v1",
            },
        },
        "compliance_check_id": "compliance_runtime_unavailable",
        "revision_attempts": 0,
        "notes": [
            "Opportunity handoff reached the operating workflow, but compliance runtime was unavailable."
        ],
        "stage_results": [],
    }


def _handoff_notes(selected, research, req) -> list[str]:
    """Explain the mode2 -> mode1 handoff in plain language for the UI."""
    coverage = req.data_intake_report.price_coverage if req.data_intake_report else 0.0
    notes = [
        f"机会引擎从种子词出发，排名第一的赛道是「{selected.keyword}」（机会分 {selected.score}）。",
        f"该赛道交给选品深度分析：在 {len(req.competitors)} 个真实竞品上跑五维打分。",
        f"五维结论：机会分 {research.score}/100，决策 {research.decision}，置信度 {research.confidence}。",
    ]
    if coverage < 0.25:
        notes.append(
            f"⚠️ 该赛道价格覆盖仅 {coverage * 100:.0f}%，利润维度已诚实降级并转人工，"
            "真实售价需对入围 ASIN 单独补齐。"
        )
    if research.score_breakdown.get("compliance", 100) < 50:
        notes.append("⚠️ 合规维度命中医疗声称措辞，已转人工核实（非硬阻断）。")
    return notes


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower())[:32]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run opportunity discovery and optional workflow handoff.")
    parser.add_argument("seed", nargs="?", default="neck massager")
    parser.add_argument("--workflow", action="store_true", help="Run listing/compliance workflow after discovery.")
    parser.add_argument("--target-price", type=float, default=None)
    parser.add_argument("--max-candidates", type=int, default=8)
    args = parser.parse_args()

    seed = args.seed
    report = (
        discover_to_workflow(seed, target_price=args.target_price, max_candidates=args.max_candidates)
        if args.workflow
        else discover_and_deep_dive(seed, target_price=args.target_price, max_candidates=args.max_candidates)
    )
    print(f"\n种子词 '{seed}' → mode2 发现 {len(report['opportunities'])} 赛道")
    print(f"→ mode1 深挖第一名：{report['selected_keyword']}\n")
    for note in report["handoff"]:
        print(f"  {note}")
    if args.workflow:
        print(f"\n→ workflow_status: {report['workflow_status']}")
        workflow = report.get("workflow") or {}
        for stage in workflow.get("stage_results") or []:
            print(f"  [{stage.get('name')}] {stage.get('decision')} - {stage.get('summary')}")


if __name__ == "__main__":
    main()
