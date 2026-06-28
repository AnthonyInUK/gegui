"""Run the cross-border ecommerce Agent-as-Tool demo pipeline.

The demo is intentionally local and deterministic:
1. Convert public Amazon-style fixture data into ProductResearchRequest.
2. Score the candidate product.
3. Generate an Amazon listing.
4. Run compliance review through the existing Compliance Tool adapter.
5. Diagnose ad metrics and gate suggested actions.
6. Draft a customer-service reply and gate risky actions.
7. Write a single JSON report for demos and interviews.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crossborder.ads.diagnostic_agent import diagnose_ads  # noqa: E402
from crossborder.customer_service.agent import respond_to_customer  # noqa: E402
from crossborder.data_intake.amazon_reviews_2023_loader import (  # noqa: E402
    build_product_research_request,
)
from crossborder.listing_agent import generate_listing_tool  # noqa: E402
from crossborder.product_research import research_product  # noqa: E402
from crossborder.schemas import (  # noqa: E402
    AdsDiagnosticRequest,
    CrossBorderRequest,
    CustomerServiceRequest,
    ListingGenerationRequest,
)


DEFAULT_META = ROOT / "tests" / "crossborder" / "fixtures" / "amazon_reviews_2023" / "meta_sample.jsonl"
DEFAULT_REVIEWS = ROOT / "tests" / "crossborder" / "fixtures" / "amazon_reviews_2023" / "review_sample.jsonl"
DEFAULT_ADS = ROOT / "examples" / "crossborder" / "ads_diagnostic_bad_acos.json"
DEFAULT_CUSTOMER = ROOT / "examples" / "crossborder" / "customer_refund_request.json"
DEFAULT_OUTPUT = ROOT / "examples" / "crossborder" / "demo_pipeline_result.json"


def run_demo_pipeline(
    *,
    meta_path: Path = DEFAULT_META,
    review_path: Path = DEFAULT_REVIEWS,
    ads_path: Path = DEFAULT_ADS,
    customer_path: Path = DEFAULT_CUSTOMER,
    output_path: Path = DEFAULT_OUTPUT,
    run_compliance: bool = True,
) -> dict[str, Any]:
    research_request = build_product_research_request(
        meta_path=meta_path,
        review_path=review_path,
        keyword="cable organizer",
        category="Office Products",
        unit_cost=4.2,
        max_competitors=5,
        workflow_id="wf_demo_crossborder_pipeline",
        seller_id="seller_demo",
    )
    research_result = research_product(research_request)
    demo_product = research_request.product.model_copy(update={"image_urls": [], "image_paths": []})

    listing_result = generate_listing_tool(
        ListingGenerationRequest(
            platform=research_request.platform,
            market=research_request.market,
            product=demo_product,
            workflow_id=research_request.workflow_id,
            seller_id=research_request.seller_id,
            keyword_hints=[point.topic for point in research_request.pain_points[:3]],
            metadata={"source": "demo_crossborder_pipeline"},
        )
    )

    compliance_request = CrossBorderRequest(
        platform=research_request.platform,
        market=research_request.market,
        workflow_id=research_request.workflow_id,
        seller_id=research_request.seller_id,
        product=demo_product,
        metadata={
            "source": "demo_crossborder_pipeline",
            "remote_images_omitted_for_offline_demo": True,
        },
    )
    if run_compliance:
        compliance_result = _run_live_compliance_or_stub(compliance_request, listing_result.listing)
    else:
        compliance_result = _offline_compliance_stub(research_request.workflow_id)

    ads_payload = json.loads(ads_path.read_text(encoding="utf-8"))
    ads_payload["workflow_id"] = research_request.workflow_id
    ads_payload["seller_id"] = research_request.seller_id
    ads_payload["asin"] = research_request.product.attributes.get("source_parent_asin", "")
    ads_payload.setdefault("metadata", {})
    ads_result = diagnose_ads(AdsDiagnosticRequest.model_validate(ads_payload))

    customer_payload = json.loads(customer_path.read_text(encoding="utf-8"))
    customer_payload["workflow_id"] = research_request.workflow_id
    customer_payload["seller_id"] = research_request.seller_id
    customer_payload["product_title"] = research_request.product.title
    customer_result = respond_to_customer(CustomerServiceRequest.model_validate(customer_payload))

    report = {
        "demo": {
            "name": "crossborder_agent_end_to_end_demo",
            "platform": research_request.platform.value,
            "market": research_request.market.value,
            "workflow_id": research_request.workflow_id,
            "seller_id": research_request.seller_id,
        },
        "input_summary": {
            "selected_product": research_request.product.model_dump(mode="json"),
            "keyword": research_request.metadata.get("keyword", ""),
            "target_category": research_request.metadata.get("category", ""),
            "target_price": research_request.target_price,
            "landed_cost": research_request.cost_model.total_landed_cost()
            if research_request.cost_model
            else research_request.landed_cost,
            "competitors": [item.model_dump(mode="json") for item in research_request.competitors],
            "pain_points": [item.model_dump(mode="json") for item in research_request.pain_points],
            "cost_model": research_request.cost_model.model_dump(mode="json")
            if research_request.cost_model
            else {},
            "logistics": research_request.logistics.model_dump(mode="json")
            if research_request.logistics
            else {},
            "compliance_precheck": research_request.compliance_precheck.model_dump(mode="json")
            if research_request.compliance_precheck
            else {},
            "selection_basis": _selection_basis(research_request, research_result),
            "listing_business_context": _listing_business_context(research_request, listing_result.model_dump(mode="json")),
        },
        "stages": {
            "data_intake": {
                "status": "pass",
                "report": research_request.data_intake_report.model_dump(mode="json")
                if research_request.data_intake_report
                else {},
            },
            "product_research": research_result.model_dump(mode="json"),
            "listing_generation": listing_result.model_dump(mode="json"),
            "compliance_check": compliance_result,
            "ads_diagnostic": ads_result.model_dump(mode="json"),
            "customer_service": customer_result.model_dump(mode="json"),
        },
        "gate_summary": _gate_summary(
            [
                *ads_result.gated_actions,
                *customer_result.gated_actions,
            ]
        ),
        "audit_summary": _audit_summary(
            research_result.model_dump(mode="json"),
            listing_result.model_dump(mode="json"),
            compliance_result,
            ads_result.model_dump(mode="json"),
            customer_result.model_dump(mode="json"),
        ),
        "final_summary": _final_summary(research_result, compliance_result, ads_result, customer_result),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _selection_basis(research_request, research_result) -> list[str]:
    product = research_request.product
    competitor_count = len(research_request.competitors)
    pain_count = len(research_request.pain_points)
    source_categories = product.attributes.get("source_categories") or []
    basis = [
        f"从公开 Amazon Reviews 2023 风格数据中按关键词 {research_request.metadata.get('keyword', '')!r} 和类目 {research_request.metadata.get('category', '')!r} 匹配候选。",
        f"最终候选为 {product.title}，类目路径为 {' > '.join(source_categories) if source_categories else product.category}。",
        f"样本中匹配到 {competitor_count} 个竞品、{pain_count} 类评论痛点，用于判断需求、竞争和差异化空间。",
        f"机会分 {research_result.score}/100，需求、利润、竞争、物流、合规五项综合后为 {research_result.opportunity_level}。",
    ]
    if research_request.cost_model and research_request.target_price is not None:
        basis.append(
            f"目标售价约 ${research_request.target_price}，预估全链路成本约 ${research_request.cost_model.total_landed_cost()}，用于粗算利润空间。"
        )
    return basis


def _listing_business_context(research_request, listing_result: dict[str, Any]) -> dict[str, Any]:
    product = research_request.product
    listing = listing_result.get("listing") or {}
    keyword = research_request.metadata.get("keyword", "")
    competitors = research_request.competitors
    pain_points = research_request.pain_points
    feature_terms = product.features[:3]
    risk_topics = [point.topic for point in pain_points]
    constraints = {
        "title_length": len(listing.get("title") or ""),
        "title_limit": 180,
        "bullet_count": len(listing.get("bullets") or []),
        "bullet_target": 5,
        "search_term_count": len(listing.get("search_terms") or []),
    }
    objectives = [
        {
            "title": "让平台知道卖什么",
            "detail": f"标题要覆盖 {keyword or product.category}、{product.category}、Desk/Clips 等核心识别词。",
        },
        {
            "title": "让买家知道为什么买",
            "detail": f"先表达 {', '.join(feature_terms) if feature_terms else '核心功能'} 这些来自商品 metadata 的确定卖点。",
        },
        {
            "title": "不把痛点写成假承诺",
            "detail": f"{', '.join(risk_topics) if risk_topics else '评论痛点'} 是风险/改良信号，不能直接写成永久解决或适配所有场景的承诺。",
        },
    ]
    gaps = [
        f"五点当前 {constraints['bullet_count']}/{constraints['bullet_target']}，还要补尺寸兼容、安装表面、包装数量/适用场景。",
        f"{', '.join(risk_topics) if risk_topics else '评论痛点'} 是研究提示，不一定能作为最终后台关键词发布。",
        "真实发布还需要主图、场景图、尺寸图、类目属性、变体、包装尺寸、FBA 费用和合规证据。",
    ]
    return {
        "generation_object": product.title,
        "candidate_pool_relation": f"候选池 {len(competitors)} 条，当前 Listing 只为最终主推商品生成。",
        "business_goal": (
            f"把这个候选品包装成 Amazon 可审核的初稿：先覆盖核心词 {keyword or product.category}，"
            f"再表达 {len(feature_terms)} 个安全卖点，不承诺解决 {', '.join(risk_topics) if risk_topics else '评论痛点'} 等质量痛点。"
        ),
        "platform_constraints": constraints,
        "objectives": objectives,
        "gaps": gaps,
        "keyword_sources": {
            "base_keyword": keyword,
            "feature_terms": feature_terms,
            "pain_point_terms": risk_topics,
        },
    }


def _offline_compliance_stub(workflow_id: str) -> dict[str, Any]:
    return {
        "decision": "pass",
        "risk_level": "low",
        "confidence": 1.0,
        "risk_categories": [],
        "issues": [],
        "required_documents": [],
        "suggested_rewrite": {},
        "human_review_required": False,
        "evidence": [
            {
                "source": "offline_demo_stub",
                "title": "Compliance skipped",
                "summary": "Compliance engine was skipped via --no-compliance for offline demos.",
            }
        ],
        "audit": {
            "check_id": "offline_compliance_stub",
            "workflow_id": workflow_id,
            "model": "offline",
            "policy_version": "offline-demo",
            "ruleset_version": "offline-demo",
            "tool_contract_version": "compliance-tool-v1",
        },
    }


def _run_live_compliance_or_stub(req: CrossBorderRequest, listing) -> dict[str, Any]:
    """Use the real compliance tool when its optional runtime is installed."""
    try:
        from crossborder.tools import check_listing_compliance
    except ModuleNotFoundError as exc:
        stub = _offline_compliance_stub(req.workflow_id)
        stub["audit"]["check_id"] = "offline_compliance_dependency_missing"
        stub["evidence"][0]["summary"] = (
            "Compliance runtime is not installed in this environment; "
            f"falling back to offline demo stub: {exc.name}."
        )
        return stub
    try:
        return check_listing_compliance(req, listing)
    except ModuleNotFoundError as exc:
        stub = _offline_compliance_stub(req.workflow_id)
        stub["audit"]["check_id"] = "offline_compliance_dependency_missing"
        stub["evidence"][0]["summary"] = (
            "Compliance runtime is not installed in this environment; "
            f"falling back to offline demo stub: {exc.name}."
        )
        return stub


def _gate_summary(gated_actions: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for action in gated_actions:
        decision = action.get("gate_decision", "unknown")
        counts[decision] = counts.get(decision, 0) + 1
    return {
        "total_actions": len(gated_actions),
        "decision_counts": counts,
        "blocked_or_human_review_actions": [
            {
                "action_type": action.get("action_type"),
                "gate_decision": action.get("gate_decision"),
                "reasons": action.get("reasons", []),
            }
            for action in gated_actions
            if action.get("gate_decision") != "allowed"
        ],
    }


def _final_summary(research_result, compliance_result: dict, ads_result, customer_result) -> dict[str, Any]:
    return {
        "product_research_decision": research_result.decision,
        "listing_compliance_decision": compliance_result.get("decision"),
        "ads_decision": ads_result.decision,
        "customer_service_decision": customer_result.decision,
        "ready_for_publish": compliance_result.get("decision") == "pass",
        "human_review_required": any(
            [
                research_result.human_review_required,
                compliance_result.get("human_review_required", False),
                ads_result.human_review_required,
                customer_result.human_review_required,
            ]
        ),
    }


def _audit_summary(
    research_result: dict[str, Any],
    listing_result: dict[str, Any],
    compliance_result: dict[str, Any],
    ads_result: dict[str, Any],
    customer_result: dict[str, Any],
) -> dict[str, Any]:
    gate_ids = []
    for stage in (ads_result, customer_result):
        for action in stage.get("gated_actions", []):
            gate_id = action.get("gate_id")
            if gate_id:
                gate_ids.append(gate_id)
    return {
        "research_id": (research_result.get("audit") or {}).get("research_id", ""),
        "listing_id": (listing_result.get("audit") or {}).get("listing_id", ""),
        "compliance_check_id": (compliance_result.get("audit") or {}).get("check_id", ""),
        "ads_diagnostic_id": (ads_result.get("audit") or {}).get("diagnostic_id", ""),
        "customer_response_id": (customer_result.get("audit") or {}).get("response_id", ""),
        "gate_ids": gate_ids,
    }


def _pretty_summary(report: dict[str, Any], stage: str | None = None) -> str:
    if stage:
        return json.dumps(report["stages"].get(stage, {}), ensure_ascii=False, indent=2)
    final = report["final_summary"]
    gate = report["gate_summary"]
    audit = report["audit_summary"]
    lines = [
        "Cross-border Agent Demo",
        f"- Product research: {final['product_research_decision']}",
        f"- Listing compliance: {final['listing_compliance_decision']}",
        f"- Ads diagnostic: {final['ads_decision']}",
        f"- Customer service: {final['customer_service_decision']}",
        f"- Ready for publish: {final['ready_for_publish']}",
        f"- Human review required: {final['human_review_required']}",
        f"- Gated actions: {gate['decision_counts']}",
        f"- Audit IDs: {audit}",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run cross-border Agent end-to-end demo pipeline.")
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    parser.add_argument("--ads", type=Path, default=DEFAULT_ADS)
    parser.add_argument("--customer", type=Path, default=DEFAULT_CUSTOMER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true", help="Print a human-readable summary instead of raw final_summary JSON.")
    parser.add_argument(
        "--stage",
        choices=[
            "data_intake",
            "product_research",
            "listing_generation",
            "compliance_check",
            "ads_diagnostic",
            "customer_service",
        ],
        help="Print a single stage from the generated report.",
    )
    parser.add_argument("--no-compliance", action="store_true", help="Skip live compliance check and use an offline pass stub.")
    args = parser.parse_args()

    report = run_demo_pipeline(
        meta_path=args.meta,
        review_path=args.reviews,
        ads_path=args.ads,
        customer_path=args.customer,
        output_path=args.output,
        run_compliance=not args.no_compliance,
    )
    if args.pretty or args.stage:
        print(_pretty_summary(report, args.stage))
    else:
        print(json.dumps(report["final_summary"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
