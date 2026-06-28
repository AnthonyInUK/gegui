"""Ads Diagnostic Agent-as-Tool wrapper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from crossborder.ads.diagnostic_agent import diagnose_ads
from crossborder.schemas import AdsCampaignSnapshot, AdsDiagnosticRequest
from crossborder.tools_agent.contracts import (
    ToolAudit,
    ToolResultEnvelope,
    ToolRuntime,
    exception_envelope,
    input_hash,
    validation_error_envelope,
)

TOOL_NAME = "crossborder.ads_diagnostic"
VERSION = "ads-diagnostic-tool-v1"


class AdsDiagnosticToolRequest(BaseModel):
    platform: str = "amazon"
    market: str = "US"
    workflow_id: str = ""
    seller_id: str = ""
    asin: str = ""
    campaigns: list[AdsCampaignSnapshot] = Field(default_factory=list)
    target_acos: float = 0.3
    min_clicks_for_conversion_judgment: int = 20
    listing_context: dict[str, Any] = Field(default_factory=dict)
    margin_context: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def run_ads_diagnostic_tool(payload: AdsDiagnosticToolRequest | dict[str, Any]) -> ToolResultEnvelope:
    workflow_id = _field(payload, "workflow_id")
    seller_id = _field(payload, "seller_id")
    try:
        req = payload if isinstance(payload, AdsDiagnosticToolRequest) else AdsDiagnosticToolRequest.model_validate(payload)
        diagnostic_req = AdsDiagnosticRequest(
            platform=req.platform,
            market=req.market,
            workflow_id=req.workflow_id,
            seller_id=req.seller_id,
            asin=req.asin,
            campaigns=req.campaigns,
            target_acos=req.target_acos,
            min_clicks_for_conversion_judgment=req.min_clicks_for_conversion_judgment,
            listing_context=req.listing_context,
            metadata={
                **req.metadata,
                "permissions": req.permissions,
                "margin_context": req.margin_context,
                "agent_tool": TOOL_NAME,
            },
        )
        result = diagnose_ads(diagnostic_req)
        return ToolResultEnvelope(
            decision=result.decision,
            human_review_required=result.human_review_required,
            confidence=_confidence(result.risk_level, result.issues),
            result={
                "metrics": result.metrics,
                "issues": result.issues,
                "recommendations": result.recommendations,
                "suggested_actions": result.suggested_actions,
                "gated_actions": result.gated_actions,
                "risk_level": result.risk_level,
            },
            errors=[],
            audit=_audit(req, result.audit),
        )
    except ValidationError as exc:
        return validation_error_envelope(
            tool_name=TOOL_NAME,
            payload=payload,
            exc=exc,
            workflow_id=workflow_id,
            seller_id=seller_id,
        )
    except Exception as exc:  # pragma: no cover - defensive envelope boundary
        return exception_envelope(
            tool_name=TOOL_NAME,
            payload=payload,
            exc=exc,
            workflow_id=workflow_id,
            seller_id=seller_id,
        )


def _confidence(risk_level: str, issues: list[dict[str, Any]]) -> float:
    if not issues:
        return 0.75
    if risk_level == "high":
        return 0.86
    if risk_level == "medium":
        return 0.8
    return 0.9


def _audit(req: AdsDiagnosticToolRequest, source_audit: dict[str, Any]) -> ToolAudit:
    return ToolAudit(
        tool_name=TOOL_NAME,
        workflow_id=req.workflow_id,
        seller_id=req.seller_id,
        runtime=ToolRuntime.deterministic_rules.value,
        version=VERSION,
        input_hash=source_audit.get("input_hash") or input_hash(req),
        created_at=source_audit.get("created_at") or ToolAudit.model_fields["created_at"].default_factory(),
        trace_id=source_audit.get("ads_diagnostic_id") or source_audit.get("diagnostic_id", ""),
        extra=dict(source_audit),
    )


def _field(payload: AdsDiagnosticToolRequest | dict[str, Any], key: str) -> str:
    if isinstance(payload, AdsDiagnosticToolRequest):
        return str(getattr(payload, key, "") or "")
    return str(payload.get(key, "") or "") if isinstance(payload, dict) else ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Ads Diagnostic Agent-as-Tool")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    envelope = run_ads_diagnostic_tool(payload)
    json.dump(envelope.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
