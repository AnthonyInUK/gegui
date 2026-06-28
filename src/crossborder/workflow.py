"""
Minimal cross-border ecommerce workflow.

Usage:
    python src/crossborder/workflow.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

from crossborder.schemas import (  # noqa: E402
    CrossBorderRequest,
    CrossBorderResult,
)
from crossborder.stages.assets import run_assets_stage  # noqa: E402
from crossborder.stages.base import WorkflowContext  # noqa: E402
from crossborder.stages.category import run_category_stage  # noqa: E402
from crossborder.stages.compliance import run_compliance_stage  # noqa: E402
from crossborder.stages.intake import run_intake_stage  # noqa: E402
from crossborder.stages.listing import run_listing_stage  # noqa: E402
from crossborder.stages.platform_rules import run_platform_rules_stage  # noqa: E402
from crossborder.stages.product_research import run_product_research_stage  # noqa: E402
from crossborder.stages.publish_gate import run_publish_gate_stage  # noqa: E402
from crossborder.stages.rewrite import run_rewrite_stage  # noqa: E402


def check_listing_compliance(req: CrossBorderRequest, listing) -> dict:
    """Lazy adapter so offline workflow imports do not require the compliance runtime."""
    from crossborder.tools import check_listing_compliance as live_check_listing_compliance

    return live_check_listing_compliance(req, listing)


def run_workflow(req: CrossBorderRequest, max_revision_attempts: int = 1) -> CrossBorderResult:
    ctx = WorkflowContext(request=req)
    run_intake_stage(ctx)
    run_product_research_stage(ctx)
    run_category_stage(ctx)
    run_listing_stage(ctx)
    run_platform_rules_stage(ctx)
    run_assets_stage(ctx)
    run_compliance_stage(ctx, check_listing_compliance)

    while (
        ctx.compliance
        and ctx.compliance.get("decision") == "requires_revision"
        and ctx.revision_attempts < max_revision_attempts
    ):
        rewrite_stage = run_rewrite_stage(ctx)
        if rewrite_stage.status == "skipped":
            break
        run_platform_rules_stage(ctx)
        run_compliance_stage(ctx, check_listing_compliance)

    status, listing_package, _ = run_publish_gate_stage(ctx)
    compliance = ctx.compliance or {}
    check_id = (compliance.get("audit") or {}).get("check_id", "")
    return CrossBorderResult(
        status=status,
        platform=ctx.request.platform,
        market=ctx.request.market,
        workflow_id=ctx.request.workflow_id,
        seller_id=ctx.request.seller_id,
        listing=ctx.listing,
        listing_package=listing_package,
        compliance=compliance,
        compliance_check_id=check_id,
        revision_attempts=ctx.revision_attempts,
        notes=ctx.notes,
        stage_results=[stage.model_dump(mode="json") for stage in ctx.stage_results],
    )


def _demo_request() -> dict[str, Any]:
    return {
        "platform": "amazon",
        "market": "US",
        "workflow_id": "wf_crossborder_demo",
        "seller_id": "seller_demo",
        "product": {
            "title": "Portable Neck Massager",
            "category": "health_personal_care",
            "features": ["portable design", "quiet operation", "gentle heat"],
            "claims": ["supports everyday muscle relaxation"],
            "materials": ["ABS", "silicone"],
            "audience": "home and office users",
        },
    }


def main() -> None:
    if len(sys.argv) > 1:
        payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    else:
        payload = _demo_request()
    result = run_workflow(CrossBorderRequest.model_validate(payload))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
