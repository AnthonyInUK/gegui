"""Unified result contract for mixed Agent-as-Tool runtimes.

The workflow should not depend on Strands, OpenAI Agents SDK, LangGraph, or any
other concrete runtime. Runtime-specific adapters map their native result into
this shape before the orchestrator consumes it.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentRuntime(str, Enum):
    deterministic = "deterministic"
    strands = "strands"
    openai_agents_sdk = "openai_agents_sdk"
    langgraph = "langgraph"
    external_http = "external_http"
    mcp = "mcp"


class AgentToolDecision(str, Enum):
    pass_ = "pass"
    requires_revision = "requires_revision"
    requires_human_review = "requires_human_review"
    blocked = "blocked"
    failed = "failed"


class AgentToolError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class AgentToolAudit(BaseModel):
    workflow_id: str = ""
    run_id: str = ""
    tool_name: str = ""
    model: str = ""
    input_hash: str = ""
    output_hash: str = ""
    latency_ms: int | None = None
    trace_ref: str = ""


class AgentToolResult(BaseModel):
    tool_name: str
    runtime: AgentRuntime
    decision: AgentToolDecision = AgentToolDecision.pass_
    confidence: float = 1.0
    issues: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    human_review_required: bool = False
    error: AgentToolError | None = None
    audit: AgentToolAudit = Field(default_factory=AgentToolAudit)

