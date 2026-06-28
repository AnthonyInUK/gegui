"""Opportunity discovery Agent-as-Tool wrapper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from pydantic import ValidationError

from crossborder.opportunity.pipeline import discover_and_deep_dive
from crossborder.schemas import OpportunityToolRequest
from crossborder.tools_agent.contracts import (
    ToolAudit,
    ToolDecision,
    ToolResultEnvelope,
    ToolRuntime,
    exception_envelope,
    input_hash,
    validation_error_envelope,
)

TOOL_NAME = "crossborder.opportunity"
VERSION = "opportunity-tool-v1"


def run_opportunity_tool(payload: OpportunityToolRequest | dict[str, Any]) -> ToolResultEnvelope:
    workflow_id = _field(payload, "workflow_id")
    seller_id = _field(payload, "seller_id")
    try:
        req = payload if isinstance(payload, OpportunityToolRequest) else OpportunityToolRequest.model_validate(payload)
        report = discover_and_deep_dive(
            req.seed_keyword,
            target_price=req.target_price,
            max_candidates=req.max_candidates,
        )
        return _envelope_from_report(req, report)
    except ValidationError as exc:
        return validation_error_envelope(
            tool_name=TOOL_NAME,
            payload=payload,
            exc=exc,
            workflow_id=workflow_id,
            seller_id=seller_id,
        )
    except Exception as exc:  # pragma: no cover - defensive boundary for network/dataset failures
        return exception_envelope(
            tool_name=TOOL_NAME,
            payload=payload,
            exc=exc,
            workflow_id=workflow_id,
            seller_id=seller_id,
        )


def _envelope_from_report(req: OpportunityToolRequest, report: dict[str, Any]) -> ToolResultEnvelope:
    selected_keyword = report.get("selected_keyword")
    if not selected_keyword:
        return ToolResultEnvelope(
            decision=ToolDecision.requires_human_review.value,
            human_review_required=True,
            confidence=0.3,
            result={
                "opportunity_count": 0,
                "note": "机会引擎未发现可执行赛道，需人工换种子词或放宽门槛。",
                "handoff": report.get("handoff", []),
            },
            errors=[],
            audit=_audit(req, report),
        )

    research = report.get("research") or {}
    decision = str(research.get("decision") or ToolDecision.requires_human_review.value)
    confidence = float(research.get("confidence") or 0.0)
    human = bool(research.get("human_review_required", decision == ToolDecision.requires_human_review.value))
    opportunities = report.get("opportunities") or []
    return ToolResultEnvelope(
        decision=decision,
        human_review_required=human,
        confidence=confidence,
        result={
            "selected_keyword": selected_keyword,
            "opportunity_count": len(opportunities),
            "top_opportunities": [_opportunity_summary(item) for item in opportunities[:5]],
            "research": {
                "decision": decision,
                "score": research.get("score"),
                "confidence": confidence,
                "score_breakdown": research.get("score_breakdown", {}),
                "human_review_required": human,
            },
            "price_coverage": (report.get("intake_report") or {}).get("price_coverage"),
            "handoff": report.get("handoff", []),
        },
        errors=[],
        audit=_audit(req, report),
    )


def _opportunity_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "keyword": item.get("keyword"),
        "score": item.get("score"),
        "rank": item.get("rank"),
        "discovery_source": item.get("discovery_source"),
    }


def _audit(req: OpportunityToolRequest, report: dict[str, Any]) -> ToolAudit:
    return ToolAudit(
        tool_name=TOOL_NAME,
        workflow_id=req.workflow_id,
        seller_id=req.seller_id,
        runtime=ToolRuntime.agent_wrapper.value,
        version=VERSION,
        input_hash=input_hash(req),
        extra={
            "seed_keyword": req.seed_keyword,
            "selected_keyword": report.get("selected_keyword"),
        },
    )


def _field(payload: OpportunityToolRequest | dict[str, Any], key: str) -> str:
    if isinstance(payload, OpportunityToolRequest):
        return str(getattr(payload, key, "") or "")
    return str(payload.get(key, "") or "") if isinstance(payload, dict) else ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Opportunity Agent-as-Tool")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    envelope = run_opportunity_tool(payload)
    json.dump(envelope.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
