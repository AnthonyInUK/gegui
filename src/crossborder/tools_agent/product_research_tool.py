"""Product Research Agent-as-Tool wrapper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from pydantic import ValidationError

from crossborder.product_research import research_product
from crossborder.schemas import ProductResearchRequest
from crossborder.tools_agent.contracts import (
    ToolAudit,
    ToolResultEnvelope,
    ToolRuntime,
    exception_envelope,
    input_hash,
    validation_error_envelope,
)

TOOL_NAME = "crossborder.product_research"
VERSION = "product-research-tool-v1"


def run_product_research_tool(payload: ProductResearchRequest | dict[str, Any]) -> ToolResultEnvelope:
    workflow_id = _field(payload, "workflow_id")
    seller_id = _field(payload, "seller_id")
    try:
        req = payload if isinstance(payload, ProductResearchRequest) else ProductResearchRequest.model_validate(payload)
        result = research_product(req)
        selected_candidate = next(
            (item for item in result.candidate_ranking if item.get("role") == "selected"),
            result.candidate_ranking[0] if result.candidate_ranking else {},
        )
        return ToolResultEnvelope(
            decision=result.decision,
            human_review_required=result.human_review_required,
            confidence=result.confidence,
            result={
                "score": result.score,
                "opportunity_level": result.opportunity_level,
                "score_breakdown": result.score_breakdown,
                "selected_candidate": selected_candidate,
                "candidate_ranking": result.candidate_ranking,
                "pain_points": [point.model_dump(mode="json") for point in req.pain_points],
                "selection_rationale": result.selection_rationale,
                "issues": result.issues,
                "suggestions": result.suggestions,
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


def _audit(req: ProductResearchRequest, source_audit: dict[str, Any]) -> ToolAudit:
    extra = dict(source_audit)
    return ToolAudit(
        tool_name=TOOL_NAME,
        workflow_id=req.workflow_id,
        seller_id=req.seller_id,
        runtime=ToolRuntime.deterministic_rules.value,
        version=VERSION,
        input_hash=source_audit.get("input_hash") or input_hash(req),
        created_at=source_audit.get("created_at") or ToolAudit.model_fields["created_at"].default_factory(),
        trace_id=source_audit.get("research_id", ""),
        extra=extra,
    )


def _field(payload: ProductResearchRequest | dict[str, Any], key: str) -> str:
    if isinstance(payload, ProductResearchRequest):
        return str(getattr(payload, key, "") or "")
    return str(payload.get(key, "") or "") if isinstance(payload, dict) else ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Product Research Agent-as-Tool")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    envelope = run_product_research_tool(payload)
    json.dump(envelope.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
