"""Amazon-first advertising diagnostic Agent-as-Tool MVP."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossborder.action_gate import evaluate_action_gate
from crossborder.schemas import (
    ActionGateRequest,
    AdsCampaignSnapshot,
    AdsDiagnosticRequest,
    AdsDiagnosticResult,
)


def diagnose_ads(req: AdsDiagnosticRequest) -> AdsDiagnosticResult:
    metrics = _aggregate_metrics(req.campaigns)
    issues = _diagnose_issues(req, metrics)
    recommendations, suggested_actions = _recommend(req, metrics, issues)
    gated_actions = _gate_actions(req, suggested_actions, _risk_level(issues))
    decision = _decision(issues)
    risk_level = _risk_level(issues)
    return AdsDiagnosticResult(
        decision=decision,
        risk_level=risk_level,
        metrics=metrics,
        issues=issues,
        recommendations=recommendations,
        suggested_actions=suggested_actions,
        gated_actions=gated_actions,
        human_review_required=any(action.get("human_review_required") for action in gated_actions),
        audit={
            "diagnostic_id": f"ads_{uuid4().hex[:12]}",
            "workflow_id": req.workflow_id,
            "tool": "crossborder.ads.diagnose",
            "runtime": "deterministic_metrics_rules",
            "input_hash": _hash(req),
            "created_at": datetime.now(UTC).isoformat(),
            "version": "ads-diagnostic-v1",
        },
    )


def _gate_actions(
    req: AdsDiagnosticRequest,
    suggested_actions: list[dict],
    risk_level: str,
) -> list[dict]:
    gated = []
    permissions = list(req.metadata.get("permissions") or [])
    for action in suggested_actions:
        gate = evaluate_action_gate(
            ActionGateRequest(
                action_type=action["action_type"],
                actor_agent="AdsDiagnosticAgent",
                workflow_id=req.workflow_id,
                seller_id=req.seller_id,
                platform=req.platform,
                market=req.market,
                payload=action,
                reason=action.get("reason", ""),
                risk_level=risk_level if action.get("requires_human_review") else "low",
                permissions=permissions,
            )
        )
        gated.append(
            {
                "action_type": action["action_type"],
                "suggested_action": action,
                "gate_decision": gate.decision.value,
                "allowed": gate.allowed,
                "human_review_required": gate.human_review_required,
                "reasons": gate.reasons,
                "required_permissions": gate.required_permissions,
                "gate_id": gate.audit.get("gate_id", ""),
            }
        )
    return gated


def _aggregate_metrics(rows: list[AdsCampaignSnapshot]) -> dict[str, float | int]:
    impressions = sum(row.impressions for row in rows)
    clicks = sum(row.clicks for row in rows)
    spend = round(sum(row.spend for row in rows), 2)
    sales = round(sum(row.sales for row in rows), 2)
    orders = sum(row.orders for row in rows)
    units = sum(row.units for row in rows)
    return {
        "campaign_count": len({row.campaign_id or row.campaign_name for row in rows}),
        "row_count": len(rows),
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "sales": sales,
        "orders": orders,
        "units": units,
        "ctr": _safe_div(clicks, impressions),
        "cvr": _safe_div(orders, clicks),
        "acos": _safe_div(spend, sales),
        "roas": _safe_div(sales, spend),
        "cpc": _safe_div(spend, clicks),
        "cpa": _safe_div(spend, orders),
    }


def _diagnose_issues(req: AdsDiagnosticRequest, metrics: dict[str, float | int]) -> list[dict]:
    issues = []
    clicks = int(metrics["clicks"])
    sales = float(metrics["sales"])
    ctr = float(metrics["ctr"])
    cvr = float(metrics["cvr"])
    acos = float(metrics["acos"])

    if clicks == 0 and int(metrics["impressions"]) > 0:
        issues.append(_issue("no_clicks", "medium", "Ads receive impressions but no clicks.", "Review main image, title, price, coupon, and keyword relevance."))
    if ctr < 0.003 and int(metrics["impressions"]) >= 1000:
        issues.append(_issue("low_ctr", "medium", "CTR is low for the observed impression volume.", "Improve creative, title relevance, offer, or keyword targeting."))
    if clicks >= req.min_clicks_for_conversion_judgment and int(metrics["orders"]) == 0:
        issues.append(_issue("no_conversion", "high", "Clicks are accumulating but no orders were attributed.", "Check listing conversion blockers: price, reviews, images, coupon, delivery promise, and keyword intent."))
    if clicks >= req.min_clicks_for_conversion_judgment and cvr < 0.04:
        issues.append(_issue("low_cvr", "high", "CVR is low after enough clicks to judge conversion.", "Tighten keywords and improve listing page conversion before scaling spend."))
    if sales > 0 and acos > req.target_acos * 1.3:
        issues.append(_issue("high_acos", "high", "ACOS is materially above target.", "Reduce bids on inefficient terms and separate winners from exploration campaigns."))
    if float(metrics["spend"]) > 0 and sales == 0 and clicks >= req.min_clicks_for_conversion_judgment:
        issues.append(_issue("wasted_spend", "high", "Spend is generating traffic without sales.", "Pause or lower bids for non-converting terms pending human review."))
    if not issues:
        issues.append(_issue("healthy", "low", "No major deterministic advertising issue detected.", "Continue monitoring and scale carefully if inventory and margin allow."))
    return issues


def _recommend(
    req: AdsDiagnosticRequest,
    metrics: dict[str, float | int],
    issues: list[dict],
) -> tuple[list[dict], list[dict]]:
    recommendations = []
    actions = []
    issue_categories = {issue["category"] for issue in issues}

    if "low_ctr" in issue_categories or "no_clicks" in issue_categories:
        recommendations.append(
            {
                "category": "creative_relevance",
                "text": "Audit main image, title, price, coupon, and keyword-to-listing relevance before raising bids.",
            }
        )
    if "no_conversion" in issue_categories or "low_cvr" in issue_categories:
        recommendations.append(
            {
                "category": "listing_conversion",
                "text": "Review listing quality, reviews, offer, delivery promise, and keyword intent; avoid scaling traffic until conversion improves.",
            }
        )
        actions.append(
            {
                "action_type": "add_negative_keyword",
                "reason": "Non-converting search terms should be reviewed for negative targeting.",
                "requires_human_review": True,
            }
        )
    if "high_acos" in issue_categories or "wasted_spend" in issue_categories:
        recommendations.append(
            {
                "category": "budget_control",
                "text": "Lower bids or pause inefficient ad groups, but route budget changes through Action Gate.",
            }
        )
        actions.append(
            {
                "action_type": "pause_campaign",
                "reason": "Campaign has inefficient or wasteful spend signals.",
                "requires_human_review": True,
            }
        )
    if not actions:
        actions.append(
            {
                "action_type": "monitor_campaign",
                "reason": "Metrics are within deterministic guardrails.",
                "requires_human_review": False,
            }
        )
    return recommendations, actions


def _decision(issues: list[dict]) -> str:
    categories = {issue["category"] for issue in issues}
    if {"wasted_spend", "no_conversion", "high_acos"} & categories:
        return "requires_human_review"
    if "healthy" in categories:
        return "pass"
    return "requires_revision"


def _risk_level(issues: list[dict]) -> str:
    severities = {issue["severity"] for issue in issues}
    if "high" in severities:
        return "high"
    if "medium" in severities:
        return "medium"
    return "low"


def _issue(category: str, severity: str, reason: str, suggestion: str) -> dict:
    return {
        "category": category,
        "severity": severity,
        "reason": reason,
        "suggestion": suggestion,
    }


def _safe_div(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(numerator / denominator, 4)


def _hash(req: AdsDiagnosticRequest) -> str:
    payload = json.dumps(req.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python src/crossborder/ads/diagnostic_agent.py <request.json>")
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = diagnose_ads(AdsDiagnosticRequest.model_validate(payload))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
