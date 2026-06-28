"""Input normalization stage."""

from __future__ import annotations

from uuid import uuid4

from crossborder.stages.base import StageMode, StageResult, WorkflowContext


def run_intake_stage(ctx: WorkflowContext) -> StageResult:
    req = ctx.request
    if not req.workflow_id:
        req = req.model_copy(update={"workflow_id": f"wf_{uuid4().hex[:12]}"})
        ctx.request = req

    artifacts = {
        "platform": req.platform.value,
        "market": req.market.value,
        "seller_id": req.seller_id,
        "workflow_id": req.workflow_id,
        "image_url_count": len(req.product.image_urls),
        "image_path_count": len(req.product.image_paths),
        "document_count": len(req.product.documents),
    }
    return ctx.add_stage(
        StageResult(
            name="intake",
            mode=StageMode.rule_only,
            summary="Normalized product intake and workflow metadata.",
            artifacts=artifacts,
        )
    )

