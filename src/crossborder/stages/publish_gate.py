"""Final workflow routing stage."""

from __future__ import annotations

from crossborder.schemas import ListingPackage, WorkflowStatus
from crossborder.stages.base import StageMode, StageResult, WorkflowContext


def status_for_decision(decision: str) -> WorkflowStatus:
    if decision == "pass":
        return WorkflowStatus.ready_to_publish
    if decision == "requires_revision":
        return WorkflowStatus.needs_revision
    if decision == "requires_human_review":
        return WorkflowStatus.needs_human_review
    return WorkflowStatus.blocked


def run_publish_gate_stage(ctx: WorkflowContext) -> tuple[WorkflowStatus, ListingPackage, StageResult]:
    if ctx.listing is None or ctx.compliance is None:
        raise ValueError("listing and compliance stages must run before publish_gate")

    decision = ctx.compliance.get("decision", "blocked")
    status = status_for_decision(decision)
    audit = ctx.compliance.get("audit") or {}
    check_id = audit.get("check_id", "")
    package = ListingPackage(
        listing=ctx.listing,
        platform=ctx.request.platform,
        market=ctx.request.market,
        seller_id=ctx.request.seller_id,
        workflow_id=ctx.request.workflow_id,
        compliance_check_id=check_id,
        ready=status == WorkflowStatus.ready_to_publish,
    )
    stage = ctx.add_stage(
        StageResult(
            name="publish_gate",
            mode=StageMode.gate,
            decision=decision,
            summary="Mapped compliance decision to workflow publish status.",
            artifacts={"status": status.value, "ready": package.ready, "check_id": check_id},
        )
    )
    return status, package, stage
