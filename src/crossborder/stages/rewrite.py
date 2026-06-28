"""Automatic rewrite stage."""

from __future__ import annotations

from crossborder.listing_agent import apply_compliance_rewrite
from crossborder.stages.base import StageMode, StageResult, WorkflowContext


def run_rewrite_stage(ctx: WorkflowContext) -> StageResult:
    if ctx.listing is None or ctx.compliance is None:
        raise ValueError("listing and compliance stages must run before rewrite")

    suggested_rewrite = ctx.compliance.get("suggested_rewrite") or {}
    if not suggested_rewrite:
        ctx.notes.append("Compliance requested revision but returned no suggested rewrite.")
        return ctx.add_stage(
            StageResult(
                name="rewrite",
                mode=StageMode.agent_required,
                status="skipped",
                decision="requires_revision",
                summary="Skipped automatic rewrite because no suggested rewrite was returned.",
            )
        )

    ctx.revision_attempts += 1
    ctx.notes.append(f"Applied compliance rewrite attempt {ctx.revision_attempts}.")
    ctx.listing = apply_compliance_rewrite(ctx.listing, suggested_rewrite)
    return ctx.add_stage(
        StageResult(
            name="rewrite",
            mode=StageMode.agent_required,
            summary="Applied one compliance-guided rewrite to the listing draft.",
            artifacts={"revision_attempt": ctx.revision_attempts},
        )
    )

