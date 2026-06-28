"""Product Improvement Agent-as-Tool wrapper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from pydantic import ValidationError

from crossborder.improvement import build_improvement_spec
from crossborder.schemas import ImprovementSpecRequest
from crossborder.tools_agent.contracts import (
    ToolAudit,
    ToolDecision,
    ToolResultEnvelope,
    ToolRuntime,
    exception_envelope,
    input_hash,
    validation_error_envelope,
)

TOOL_NAME = "crossborder.improvement"
VERSION = "improvement-tool-v1"


def run_improvement_tool(payload: ImprovementSpecRequest | dict[str, Any]) -> ToolResultEnvelope:
    workflow_id = _field(payload, "workflow_id")
    seller_id = _field(payload, "seller_id")
    try:
        req = payload if isinstance(payload, ImprovementSpecRequest) else ImprovementSpecRequest.model_validate(payload)
        spec = build_improvement_spec(
            req.pain_points,
            product_title=req.product_title,
            keyword=req.keyword,
        )
        has_requirements = bool(spec.requirements)
        return ToolResultEnvelope(
            decision=ToolDecision.pass_.value if has_requirements else ToolDecision.requires_human_review.value,
            human_review_required=not has_requirements,
            confidence=0.75 if has_requirements else 0.3,
            result={
                "requirements": [item.model_dump(mode="json") for item in spec.requirements],
                "differentiation_bullets": spec.differentiation_bullets,
                "emphasis_keywords": spec.emphasis_keywords,
                "honesty_note": spec.honesty_note
                if has_requirements
                else "无评论痛点，无法生成改良需求，需人工补充。",
            },
            errors=[],
            audit=_audit(req, spec.audit),
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


def _audit(req: ImprovementSpecRequest, source_audit: dict[str, Any]) -> ToolAudit:
    extra = dict(source_audit)
    return ToolAudit(
        tool_name=TOOL_NAME,
        workflow_id=req.workflow_id,
        seller_id=req.seller_id,
        runtime=ToolRuntime.deterministic_rules.value,
        version=VERSION,
        input_hash=source_audit.get("input_hash") or input_hash(req),
        created_at=source_audit.get("created_at") or ToolAudit.model_fields["created_at"].default_factory(),
        trace_id=source_audit.get("input_hash", "")[:16],
        extra=extra,
    )


def _field(payload: ImprovementSpecRequest | dict[str, Any], key: str) -> str:
    if isinstance(payload, ImprovementSpecRequest):
        return str(getattr(payload, key, "") or "")
    return str(payload.get(key, "") or "") if isinstance(payload, dict) else ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Product Improvement Agent-as-Tool")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    envelope = run_improvement_tool(payload)
    json.dump(envelope.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
