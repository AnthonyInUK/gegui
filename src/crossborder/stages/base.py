"""Shared stage primitives for the cross-border workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from crossborder.schemas import CrossBorderRequest, ListingDraft


class StageMode(str, Enum):
    rule_only = "rule_only"
    agent_required = "agent_required"
    rule_first_agent_fallback = "rule_first_agent_fallback"
    tool_call = "tool_call"
    gate = "gate"


class StageResult(BaseModel):
    name: str
    mode: StageMode
    status: str = "ok"
    decision: str = "pass"
    summary: str = ""
    artifacts: dict[str, Any] = Field(default_factory=dict)
    issues: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class WorkflowContext:
    request: CrossBorderRequest
    listing: ListingDraft | None = None
    compliance: dict[str, Any] | None = None
    revision_attempts: int = 0
    notes: list[str] = field(default_factory=list)
    stage_results: list[StageResult] = field(default_factory=list)
    derived: dict[str, Any] = field(default_factory=dict)

    def add_stage(self, result: StageResult) -> StageResult:
        self.stage_results.append(result)
        return result

