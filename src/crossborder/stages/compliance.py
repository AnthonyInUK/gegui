"""Compliance Agent-as-Tool stage."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from crossborder.schemas import CrossBorderRequest, ListingDraft
from crossborder.stages.base import StageMode, StageResult, WorkflowContext

ComplianceChecker = Callable[[CrossBorderRequest, ListingDraft], dict[str, Any]]


def run_compliance_stage(ctx: WorkflowContext, checker: ComplianceChecker) -> StageResult:
    if ctx.listing is None:
        raise ValueError("listing stage must run before compliance")

    ctx.compliance = checker(ctx.request, ctx.listing)
    audit = ctx.compliance.get("audit") or {}
    return ctx.add_stage(
        StageResult(
            name="compliance",
            mode=StageMode.tool_call,
            decision=ctx.compliance.get("decision", "failed"),
            summary="Called Compliance Agent-as-Tool and received structured decision.",
            artifacts={
                "check_id": audit.get("check_id", ""),
                "risk_level": ctx.compliance.get("risk_level", ""),
                "human_review_required": ctx.compliance.get("human_review_required", False),
            },
            issues=ctx.compliance.get("issues") or [],
        )
    )

