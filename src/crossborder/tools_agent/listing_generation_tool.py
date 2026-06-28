"""Listing Generation Agent-as-Tool wrapper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from crossborder.listing_agent import generate_listing_tool
from crossborder.platforms import get_platform_policy
from crossborder.schemas import ListingGenerationRequest, ProductBrief, ReviewPainPoint
from crossborder.tools_agent.contracts import (
    ToolAudit,
    ToolResultEnvelope,
    ToolRuntime,
    exception_envelope,
    input_hash,
    validation_error_envelope,
)

TOOL_NAME = "crossborder.listing_generation"
VERSION = "listing-generation-tool-v1"


class ListingGenerationToolRequest(BaseModel):
    platform: str = "amazon"
    market: str = "US"
    workflow_id: str = ""
    seller_id: str = ""
    product: ProductBrief
    keyword_hints: list[str] = Field(default_factory=list)
    pain_points: list[ReviewPainPoint] = Field(default_factory=list)
    compliance_constraints: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


def run_listing_generation_tool(payload: ListingGenerationToolRequest | dict[str, Any]) -> ToolResultEnvelope:
    workflow_id = _field(payload, "workflow_id")
    seller_id = _field(payload, "seller_id")
    try:
        req = payload if isinstance(payload, ListingGenerationToolRequest) else ListingGenerationToolRequest.model_validate(payload)
        keyword_hints = _merge_keyword_hints(req)
        generation_req = ListingGenerationRequest(
            platform=req.platform,
            market=req.market,
            workflow_id=req.workflow_id,
            seller_id=req.seller_id,
            product=req.product,
            keyword_hints=keyword_hints,
            metadata={
                **req.metadata,
                "compliance_constraints": req.compliance_constraints,
                "agent_tool": TOOL_NAME,
            },
        )
        result = generate_listing_tool(generation_req)
        policy = get_platform_policy(generation_req.platform)
        return ToolResultEnvelope(
            decision=result.decision,
            human_review_required=result.human_review_required,
            confidence=result.confidence,
            result={
                "listing": result.listing.model_dump(mode="json"),
                "platform_constraints": {
                    "platform": policy.platform.value,
                    "title_limit": policy.title_limit,
                    "bullet_limit": policy.bullet_limit,
                    "bullet_count": policy.bullet_count,
                    "search_terms_limit": policy.search_terms_limit,
                    "description_limit": policy.description_limit,
                },
                "issues": result.issues,
                "suggestions": result.suggestions,
                "source_fields_used": _source_fields_used(req, keyword_hints),
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


def _merge_keyword_hints(req: ListingGenerationToolRequest) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for term in [*req.keyword_hints, *(point.topic for point in req.pain_points)]:
        normalized = term.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(term.strip())
    return merged


def _source_fields_used(req: ListingGenerationToolRequest, keyword_hints: list[str]) -> dict[str, Any]:
    return {
        "title": bool(req.product.title),
        "brand": bool(req.product.brand),
        "features_count": len(req.product.features),
        "claims_count": len(req.product.claims),
        "materials_count": len(req.product.materials),
        "keyword_hints_count": len(keyword_hints),
        "pain_points_count": len(req.pain_points),
        "compliance_constraints": sorted(req.compliance_constraints.keys()),
    }


def _audit(req: ListingGenerationToolRequest, source_audit: dict[str, Any]) -> ToolAudit:
    return ToolAudit(
        tool_name=TOOL_NAME,
        workflow_id=req.workflow_id,
        seller_id=req.seller_id,
        runtime=ToolRuntime.deterministic_template.value,
        version=VERSION,
        input_hash=source_audit.get("input_hash") or input_hash(req),
        created_at=source_audit.get("created_at") or ToolAudit.model_fields["created_at"].default_factory(),
        trace_id=source_audit.get("listing_id", ""),
        extra=dict(source_audit),
    )


def _field(payload: ListingGenerationToolRequest | dict[str, Any], key: str) -> str:
    if isinstance(payload, ListingGenerationToolRequest):
        return str(getattr(payload, key, "") or "")
    return str(payload.get(key, "") or "") if isinstance(payload, dict) else ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Listing Generation Agent-as-Tool")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    envelope = run_listing_generation_tool(payload)
    json.dump(envelope.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
