"""Tool adapters used by the cross-border workflow."""

from __future__ import annotations

from types import SimpleNamespace
from crossborder.platforms import get_platform_policy
from crossborder.schemas import CrossBorderRequest, ListingDraft

run_compliance_check = None


def check_listing_compliance(req: CrossBorderRequest, listing: ListingDraft) -> dict:
    metadata = {
        "seller_id": req.seller_id,
        "workflow_id": req.workflow_id,
        "crossborder_agent": True,
        **req.metadata,
    }
    request = _build_compliance_request(req, listing, metadata)
    runner = _get_compliance_runner()
    response = runner(request)
    result = response.model_dump(mode="json")
    return _apply_platform_preflight(req, listing, result)


def _get_compliance_runner():
    global run_compliance_check
    if run_compliance_check is not None:
        return run_compliance_check

    from core.tool_contract import run_compliance_check as live_run_compliance_check

    run_compliance_check = live_run_compliance_check
    return run_compliance_check


def _build_compliance_request(req: CrossBorderRequest, listing: ListingDraft, metadata: dict):
    try:
        from core.tool_contract import (
            CallerInput,
            ComplianceCheckRequest,
            ContentInput,
            ProductInput,
            TaskType,
        )

        return ComplianceCheckRequest(
            task_type=TaskType.listing_review,
            platform=req.platform.value,
            market=req.market.value,
            product=ProductInput(
                title=req.product.title,
                category=req.product.category,
                claims=req.product.claims,
                materials=req.product.materials,
                attributes=req.product.attributes,
            ),
            content=ContentInput(
                title=listing.title,
                description=listing.description,
                ad_copy=listing.as_ad_copy(),
                image_urls=req.product.image_urls,
                image_paths=req.product.image_paths,
            ),
            documents=req.product.documents,
            caller=CallerInput(
                agent="CrossBorderAgent",
                workflow_id=req.workflow_id,
                permissions=["read", "analyze", "suggest", "block"],
            ),
            metadata=metadata,
        )
    except ModuleNotFoundError:
        return SimpleNamespace(
            task_type="listing_review",
            platform=req.platform.value,
            market=req.market.value,
            product=SimpleNamespace(
                title=req.product.title,
                category=req.product.category,
                claims=req.product.claims,
                materials=req.product.materials,
                attributes=req.product.attributes,
            ),
            content=SimpleNamespace(
                title=listing.title,
                description=listing.description,
                ad_copy=listing.as_ad_copy(),
                image_urls=req.product.image_urls,
                image_paths=req.product.image_paths,
            ),
            documents=req.product.documents,
            caller=SimpleNamespace(
                agent="CrossBorderAgent",
                workflow_id=req.workflow_id,
                permissions=["read", "analyze", "suggest", "block"],
            ),
            metadata=metadata,
        )


def _apply_platform_preflight(req: CrossBorderRequest, listing: ListingDraft, compliance: dict) -> dict:
    policy_issues = get_platform_policy(req.platform).preflight_issues(req.product, listing)
    if not policy_issues or compliance.get("decision") != "pass":
        return compliance

    merged = dict(compliance)
    merged["decision"] = "requires_revision"
    merged["risk_level"] = "medium"
    merged["risk_categories"] = sorted(
        {
            *(merged.get("risk_categories") or []),
            *(issue["category"] for issue in policy_issues),
        }
    )
    merged["issues"] = [*(merged.get("issues") or []), *policy_issues]
    merged["suggested_rewrite"] = {
        **(merged.get("suggested_rewrite") or {}),
        "ad_copy": "Designed to support everyday comfort and relaxation during normal use.",
    }
    merged.setdefault("evidence", []).append(
        {
            "source": "crossborder_platform_policy",
            "title": f"{req.platform.value} claim preflight",
            "summary": "Detected marketplace-sensitive health or absolute claims before publish.",
        }
    )
    return merged
