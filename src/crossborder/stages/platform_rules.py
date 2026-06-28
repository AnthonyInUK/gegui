"""Marketplace rule normalization stage."""

from __future__ import annotations

from crossborder.platforms import get_platform_policy
from crossborder.stages.base import StageMode, StageResult, WorkflowContext


def run_platform_rules_stage(ctx: WorkflowContext) -> StageResult:
    if ctx.listing is None:
        raise ValueError("listing stage must run before platform_rules")

    policy = get_platform_policy(ctx.request.platform)
    ctx.listing = policy.normalize_listing(ctx.listing)
    issues = policy.preflight_issues(ctx.request.product, ctx.listing)
    return ctx.add_stage(
        StageResult(
            name="platform_rules",
            mode=StageMode.rule_only,
            decision="requires_revision" if issues else "pass",
            summary="Applied platform length, bullet, keyword, and claim preflight rules.",
            artifacts={
                "title_limit": policy.title_limit,
                "bullet_limit": policy.bullet_limit,
                "bullet_count": policy.bullet_count,
                "description_limit": policy.description_limit,
            },
            issues=issues,
        )
    )

