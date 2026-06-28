"""
MCP server for the compliance Agent-as-Tool.

Run with:
    python src/mcp_server.py

This exposes the existing compliance engine to external agents through MCP
without duplicating the FastAPI or ReviewEngine business logic.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

from core.tool_contract import (  # noqa: E402
    CallerInput,
    ComplianceCheckRequest,
    ContentInput,
    DocumentInput,
    ProductInput,
    TaskType,
    run_compliance_check,
)
from crossborder.action_gate import evaluate_action_gate  # noqa: E402
from crossborder.ads.diagnostic_agent import diagnose_ads  # noqa: E402
from crossborder.customer_service.agent import respond_to_customer  # noqa: E402
from crossborder.listing_agent import generate_listing_tool  # noqa: E402
from crossborder.product_research import research_product  # noqa: E402
from crossborder.schemas import (  # noqa: E402
    ActionGateRequest,
    AdsDiagnosticRequest,
    CrossBorderRequest,
    CustomerServiceRequest,
    ListingGenerationRequest,
    ProductResearchRequest,
)
from crossborder.workflow import run_workflow  # noqa: E402

mcp = FastMCP(
    name="hoyoverse-compliance-agent",
    instructions=(
        "Compliance Agent-as-Tool for cross-border ecommerce workflows. "
        "Use these tools to review listing copy, ad claims, product images, "
        "and certificates. Tools return structured decisions for workflow "
        "routing; they do not publish, delete, appeal, or mutate external platforms."
    ),
)


def _check(
    *,
    task_type: TaskType,
    platform: str = "",
    market: str = "CN",
    product: dict[str, Any] | None = None,
    content: dict[str, Any] | None = None,
    documents: list[dict[str, Any]] | None = None,
    caller: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    req = ComplianceCheckRequest(
        task_type=task_type,
        platform=platform,
        market=market,
        product=ProductInput.model_validate(product or {}),
        content=ContentInput.model_validate(content or {}),
        documents=[DocumentInput.model_validate(d) for d in (documents or [])],
        caller=CallerInput.model_validate(caller or {}),
        metadata=metadata or {},
    )
    return run_compliance_check(req).model_dump(mode="json")


@mcp.tool()
def compliance_check(
    task_type: str = "ad_review",
    platform: str = "",
    market: str = "CN",
    product: dict[str, Any] | None = None,
    content: dict[str, Any] | None = None,
    documents: list[dict[str, Any]] | None = None,
    caller: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a general compliance check and return a structured workflow decision.

    Use this when the caller chooses the task type dynamically. Supported
    task_type values are: ad_review, listing_review, product_eligibility,
    certificate_verification.
    """
    return _check(
        task_type=TaskType(task_type),
        platform=platform,
        market=market,
        product=product,
        content=content,
        documents=documents,
        caller=caller,
        metadata=metadata,
    )


@mcp.tool()
def compliance_check_ad(
    platform: str,
    market: str,
    product: dict[str, Any],
    content: dict[str, Any],
    documents: list[dict[str, Any]] | None = None,
    caller: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Review ecommerce ad/listing copy and images for policy and legal risk.

    Provide product title/category/claims plus content title/description/ad_copy.
    For current local execution, pass local image paths in content.image_paths.
    """
    return _check(
        task_type=TaskType.ad_review,
        platform=platform,
        market=market,
        product=product,
        content=content,
        documents=documents,
        caller=caller,
        metadata=metadata,
    )


@mcp.tool()
def compliance_check_listing(
    platform: str,
    market: str,
    product: dict[str, Any],
    content: dict[str, Any],
    documents: list[dict[str, Any]] | None = None,
    caller: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Review a product listing before publish/update workflow steps."""
    return _check(
        task_type=TaskType.listing_review,
        platform=platform,
        market=market,
        product=product,
        content=content,
        documents=documents,
        caller=caller,
        metadata=metadata,
    )


@mcp.tool()
def compliance_verify_certificate(
    platform: str = "",
    market: str = "CN",
    product: dict[str, Any] | None = None,
    content: dict[str, Any] | None = None,
    documents: list[dict[str, Any]] | None = None,
    caller: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify submitted certificate/license images against declared category."""
    return _check(
        task_type=TaskType.certificate_verification,
        platform=platform,
        market=market,
        product=product,
        content=content,
        documents=documents,
        caller=caller,
        metadata=metadata,
    )


@mcp.tool()
def crossborder_generate_listing(
    product: dict[str, Any],
    platform: str = "amazon",
    market: str = "US",
    workflow_id: str = "",
    seller_id: str = "",
    metadata: dict[str, Any] | None = None,
    max_revision_attempts: int = 1,
) -> dict[str, Any]:
    """Generate a cross-border ecommerce listing and run compliance routing.

    This tool does not publish to Amazon, Temu, Walmart, or any other platform.
    It returns a listing package plus workflow status for the caller to route.
    """
    req = CrossBorderRequest.model_validate(
        {
            "platform": platform,
            "market": market,
            "workflow_id": workflow_id,
            "seller_id": seller_id,
            "product": product,
            "metadata": metadata or {},
        }
    )
    return run_workflow(req, max_revision_attempts=max_revision_attempts).model_dump(mode="json")


@mcp.tool()
def crossborder_product_research(
    product: dict[str, Any],
    platform: str = "amazon",
    market: str = "US",
    workflow_id: str = "",
    seller_id: str = "",
    target_price: float | None = None,
    landed_cost: float | None = None,
    monthly_search_volume: int | None = None,
    competitor_count: int | None = None,
    avg_rating: float | None = None,
    review_pain_points: list[str] | None = None,
    competitors: list[dict[str, Any]] | None = None,
    pain_points: list[dict[str, Any]] | None = None,
    cost_model: dict[str, Any] | None = None,
    logistics: dict[str, Any] | None = None,
    compliance_precheck: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score a candidate product before sourcing or listing workflow.

    This is advisory. It does not place orders, publish listings, or mutate any
    external marketplace. It returns a structured opportunity score and routing
    decision for the caller's workflow.
    """
    req = ProductResearchRequest.model_validate(
        {
            "platform": platform,
            "market": market,
            "workflow_id": workflow_id,
            "seller_id": seller_id,
            "product": product,
            "target_price": target_price,
            "landed_cost": landed_cost,
            "monthly_search_volume": monthly_search_volume,
            "competitor_count": competitor_count,
            "avg_rating": avg_rating,
            "review_pain_points": review_pain_points or [],
            "competitors": competitors or [],
            "pain_points": pain_points or [],
            "cost_model": cost_model,
            "logistics": logistics,
            "compliance_precheck": compliance_precheck,
            "metadata": metadata or {},
        }
    )
    return research_product(req).model_dump(mode="json")


@mcp.tool()
def crossborder_generate_listing_draft(
    product: dict[str, Any],
    platform: str = "amazon",
    market: str = "US",
    workflow_id: str = "",
    seller_id: str = "",
    locale: str = "en-US",
    tone: str = "marketplace_native",
    keyword_hints: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a platform-aware listing draft without compliance routing.

    Use this when a caller wants only title/bullets/description/search terms.
    Use crossborder_generate_listing for the full workflow with compliance.
    """
    req = ListingGenerationRequest.model_validate(
        {
            "platform": platform,
            "market": market,
            "workflow_id": workflow_id,
            "seller_id": seller_id,
            "product": product,
            "locale": locale,
            "tone": tone,
            "keyword_hints": keyword_hints or [],
            "metadata": metadata or {},
        }
    )
    return generate_listing_tool(req).model_dump(mode="json")


@mcp.tool()
def crossborder_ads_diagnose(
    campaigns: list[dict[str, Any]],
    platform: str = "amazon",
    market: str = "US",
    workflow_id: str = "",
    seller_id: str = "",
    asin: str = "",
    target_acos: float = 0.3,
    min_clicks_for_conversion_judgment: int = 20,
    listing_context: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Diagnose ad metrics and return recommendations plus gated action suggestions."""
    req = AdsDiagnosticRequest.model_validate(
        {
            "platform": platform,
            "market": market,
            "workflow_id": workflow_id,
            "seller_id": seller_id,
            "asin": asin,
            "target_acos": target_acos,
            "min_clicks_for_conversion_judgment": min_clicks_for_conversion_judgment,
            "campaigns": campaigns,
            "listing_context": listing_context or {},
            "metadata": metadata or {},
        }
    )
    return diagnose_ads(req).model_dump(mode="json")


@mcp.tool()
def crossborder_action_gate(
    action_type: str,
    actor_agent: str = "",
    workflow_id: str = "",
    seller_id: str = "",
    platform: str = "amazon",
    market: str = "US",
    payload: dict[str, Any] | None = None,
    reason: str = "",
    risk_level: str = "medium",
    permissions: list[str] | None = None,
) -> dict[str, Any]:
    """Gate high-risk actions such as publish, price changes, budget changes, refunds, and appeals."""
    req = ActionGateRequest.model_validate(
        {
            "action_type": action_type,
            "actor_agent": actor_agent,
            "workflow_id": workflow_id,
            "seller_id": seller_id,
            "platform": platform,
            "market": market,
            "payload": payload or {},
            "reason": reason,
            "risk_level": risk_level,
            "permissions": permissions or [],
        }
    )
    return evaluate_action_gate(req).model_dump(mode="json")


@mcp.tool()
def crossborder_customer_service_respond(
    buyer_message: str,
    platform: str = "amazon",
    market: str = "US",
    workflow_id: str = "",
    seller_id: str = "",
    order_id: str = "",
    product_title: str = "",
    order_status: str = "",
    delivery_status: str = "",
    days_since_delivery: int | None = None,
    return_window_days: int = 30,
    customer_history: dict[str, Any] | None = None,
    policies: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a buyer message, draft a reply, and gate risky customer-service actions."""
    req = CustomerServiceRequest.model_validate(
        {
            "platform": platform,
            "market": market,
            "workflow_id": workflow_id,
            "seller_id": seller_id,
            "order_id": order_id,
            "buyer_message": buyer_message,
            "product_title": product_title,
            "order_status": order_status,
            "delivery_status": delivery_status,
            "days_since_delivery": days_since_delivery,
            "return_window_days": return_window_days,
            "customer_history": customer_history or {},
            "policies": policies or {},
            "metadata": metadata or {},
        }
    )
    return respond_to_customer(req).model_dump(mode="json")


if __name__ == "__main__":
    mcp.run()
