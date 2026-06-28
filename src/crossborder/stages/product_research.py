"""Product opportunity preflight stage."""

from __future__ import annotations

from crossborder.product_research import research_product
from crossborder.schemas import (
    CompetitorSnapshot,
    CompliancePrecheck,
    CostModel,
    LogisticsProfile,
    ProductResearchRequest,
    ReviewPainPoint,
)
from crossborder.stages.base import StageMode, StageResult, WorkflowContext


def run_product_research_stage(ctx: WorkflowContext) -> StageResult:
    req = ctx.request
    attrs = req.product.attributes
    research = research_product(
        ProductResearchRequest(
            platform=req.platform,
            market=req.market,
            product=req.product,
            workflow_id=req.workflow_id,
            seller_id=req.seller_id,
            target_price=_maybe_float(attrs.get("target_price")),
            landed_cost=_maybe_float(attrs.get("landed_cost")),
            monthly_search_volume=_maybe_int(attrs.get("monthly_search_volume")),
            competitor_count=_maybe_int(attrs.get("competitor_count")),
            avg_rating=_maybe_float(attrs.get("avg_rating")),
            review_pain_points=list(attrs.get("review_pain_points") or []),
            competitors=_parse_list(attrs.get("competitors"), CompetitorSnapshot),
            pain_points=_parse_list(attrs.get("pain_points"), ReviewPainPoint),
            cost_model=_parse_one(attrs.get("cost_model"), CostModel),
            logistics=_parse_one(attrs.get("logistics"), LogisticsProfile),
            compliance_precheck=_parse_one(attrs.get("compliance_precheck"), CompliancePrecheck),
            metadata=req.metadata,
        )
    )
    ctx.derived["product_research"] = research.model_dump(mode="json")
    if research.decision != "pass" and research.confidence >= 0.6:
        ctx.notes.append(
            f"Product research advisory: {research.decision} with score {research.score}."
        )
    elif research.confidence < 0.6:
        ctx.notes.append(
            f"Product research advisory has low confidence ({research.confidence}); provide market data for sourcing decisions."
        )
    return ctx.add_stage(
        StageResult(
            name="product_research",
            mode=StageMode.rule_first_agent_fallback,
            decision=research.decision,
            summary="Scored product opportunity across demand, profit, competition, logistics, and compliance.",
            artifacts={
                "score": research.score,
                "opportunity_level": research.opportunity_level,
                "confidence": research.confidence,
                "score_breakdown": research.score_breakdown,
                "research_id": research.audit.get("research_id", ""),
            },
            issues=research.issues,
        )
    )


def _maybe_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_one(value, model_cls):
    if not value:
        return None
    if isinstance(value, model_cls):
        return value
    if isinstance(value, dict):
        return model_cls.model_validate(value)
    return None


def _parse_list(value, model_cls):
    if not value:
        return []
    return [item if isinstance(item, model_cls) else model_cls.model_validate(item) for item in value]
