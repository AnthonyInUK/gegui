"""Stable contracts shared by cross-border Agent-as-Tool wrappers."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError


class ToolDecision(str, Enum):
    pass_ = "pass"
    requires_revision = "requires_revision"
    requires_human_review = "requires_human_review"
    blocked = "blocked"
    failed = "failed"


class ToolRuntime(str, Enum):
    deterministic_rules = "deterministic_rules"
    deterministic_template = "deterministic_template"
    agent_wrapper = "agent_wrapper"


class ToolError(BaseModel):
    code: str
    message: str
    field: str = ""


class ToolAudit(BaseModel):
    tool_name: str
    workflow_id: str = ""
    seller_id: str = ""
    runtime: str = ToolRuntime.agent_wrapper.value
    version: str = "agent-tool-v1"
    input_hash: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    trace_id: str = Field(default_factory=lambda: f"tool_{uuid4().hex[:12]}")
    extra: dict[str, Any] = Field(default_factory=dict)


class ToolResultEnvelope(BaseModel):
    decision: str = ToolDecision.failed.value
    human_review_required: bool = False
    confidence: float = 0.0
    result: dict[str, Any] = Field(default_factory=dict)
    errors: list[ToolError] = Field(default_factory=list)
    audit: ToolAudit


def input_hash(payload: Any) -> str:
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def validation_error_envelope(
    *,
    tool_name: str,
    payload: Any,
    exc: ValidationError,
    workflow_id: str = "",
    seller_id: str = "",
) -> ToolResultEnvelope:
    errors = [
        ToolError(
            code="invalid_input",
            message=str(error.get("msg", "")),
            field=".".join(str(part) for part in error.get("loc", ())),
        )
        for error in exc.errors()
    ]
    return ToolResultEnvelope(
        decision=ToolDecision.failed.value,
        human_review_required=True,
        confidence=0.0,
        result={},
        errors=errors,
        audit=ToolAudit(
            tool_name=tool_name,
            workflow_id=workflow_id,
            seller_id=seller_id,
            runtime=ToolRuntime.agent_wrapper.value,
            input_hash=input_hash(payload),
        ),
    )


def exception_envelope(
    *,
    tool_name: str,
    payload: Any,
    exc: Exception,
    workflow_id: str = "",
    seller_id: str = "",
) -> ToolResultEnvelope:
    return ToolResultEnvelope(
        decision=ToolDecision.failed.value,
        human_review_required=True,
        confidence=0.0,
        result={},
        errors=[
            ToolError(
                code="tool_execution_failed",
                message=str(exc),
            )
        ],
        audit=ToolAudit(
            tool_name=tool_name,
            workflow_id=workflow_id,
            seller_id=seller_id,
            runtime=ToolRuntime.agent_wrapper.value,
            input_hash=input_hash(payload),
        ),
    )
