"""Listing generation stage."""

from __future__ import annotations

from crossborder.listing_agent import generate_listing_tool
from crossborder.schemas import ListingGenerationRequest
from crossborder.stages.base import StageMode, StageResult, WorkflowContext


def run_listing_stage(ctx: WorkflowContext) -> StageResult:
    result = generate_listing_tool(
        ListingGenerationRequest(
            platform=ctx.request.platform,
            market=ctx.request.market,
            product=ctx.request.product,
            workflow_id=ctx.request.workflow_id,
            seller_id=ctx.request.seller_id,
            keyword_hints=list(ctx.request.metadata.get("keyword_hints") or []),
            metadata=ctx.request.metadata,
        )
    )
    ctx.listing = result.listing
    ctx.derived["listing_generation"] = result.model_dump(mode="json")
    return ctx.add_stage(
        StageResult(
            name="listing",
            mode=StageMode.agent_required,
            decision=result.decision,
            summary="Generated marketplace listing draft.",
            artifacts={
                "title": ctx.listing.title,
                "bullet_count": len(ctx.listing.bullets),
                "search_term_count": len(ctx.listing.search_terms),
                "confidence": result.confidence,
                "listing_id": result.audit.get("listing_id", ""),
                "runtime": result.audit.get("runtime", ""),
            },
            issues=result.issues,
        )
    )
