"""Rule-first category classification stage."""

from __future__ import annotations

from crossborder.stages.base import StageMode, StageResult, WorkflowContext


_CATEGORY_FAMILIES = {
    "health": {"health", "personal_care", "massager", "therapy", "medical"},
    "apparel": {"apparel", "clothing", "shirt", "dress", "skirt"},
    "home": {"home", "kitchen", "cleaning", "vacuum", "robot"},
    "beauty": {"beauty", "cosmetic", "skin", "hair"},
    "electronics": {"electronics", "charger", "cable", "device"},
}


def run_category_stage(ctx: WorkflowContext) -> StageResult:
    product = ctx.request.product
    text = f"{product.category} {product.title}".lower()
    family = "general"
    for candidate, keywords in _CATEGORY_FAMILIES.items():
        if any(keyword in text for keyword in keywords):
            family = candidate
            break

    ctx.derived["category_family"] = family
    return ctx.add_stage(
        StageResult(
            name="category",
            mode=StageMode.rule_first_agent_fallback,
            summary="Classified category with deterministic keyword rules.",
            artifacts={"category": product.category, "category_family": family},
        )
    )

